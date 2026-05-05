class BackgroundAudioPlayer:
    def __init__(
        self,
        *,
        ambient_sound: NotGivenOr[AudioSource | AudioConfig | list[AudioConfig] | None] = NOT_GIVEN,
        thinking_sound: NotGivenOr[
            AudioSource | AudioConfig | list[AudioConfig] | None
        ] = NOT_GIVEN,
        stream_timeout_ms: int = 200,
    ) -> None:
        """
        Initializes the BackgroundAudio component with optional ambient and thinking sounds.

        This component creates and publishes a continuous audio track to a LiveKit room while managing
        the playback of ambient and agent “thinking” sounds. It supports three types of audio sources:
        - A BuiltinAudioClip enum value, which will use a pre-defined sound from the package resources
        - A file path (string) pointing to an audio file, which can be looped.
        - An AsyncIterator that yields rtc.AudioFrame

        When a list (or AudioConfig) is supplied, the component considers each sound’s volume and probability:
        - The probability value determines the chance that a particular sound is selected for playback.
        - A total probability below 1.0 means there is a chance no sound will be selected (resulting in silence).

        Args:
            ambient_sound (NotGivenOr[Union[AudioSource, AudioConfig, List[AudioConfig], None]], optional):
                The ambient sound to be played continuously. For file paths, the sound will be looped.
                For AsyncIterator sources, ensure the iterator is infinite or looped.

            thinking_sound (NotGivenOr[Union[AudioSource, AudioConfig, List[AudioConfig], None]], optional):
                The sound to be played when the associated agent enters a “thinking” state. This can be a single
                sound source or a list of AudioConfig objects (with volume and probability settings).

        """  # noqa: E501

        self._ambient_sound = ambient_sound if is_given(ambient_sound) else None
        self._thinking_sound = thinking_sound if is_given(thinking_sound) else None

        self._audio_source = rtc.AudioSource(48000, 1, queue_size_ms=_AUDIO_SOURCE_BUFFER_MS)
        self._audio_mixer = rtc.AudioMixer(
            48000, 1, blocksize=4800, capacity=1, stream_timeout_ms=stream_timeout_ms
        )
        self.publication: rtc.LocalTrackPublication | None = None
        self._lock = asyncio.Lock()

        self._republish_task: asyncio.Task[None] | None = None  # republish the task on reconnect
        self._mixer_atask: asyncio.Task[None] | None = None

        self._play_tasks: list[asyncio.Task[None]] = []

        self._ambient_handle: PlayHandle | None = None
        self._thinking_handle: PlayHandle | None = None

    def _select_sound_from_list(self, sounds: list[AudioConfig]) -> AudioConfig | None:
        """
        Selects a sound from a list of BackgroundSound based on their probabilities.
        Returns None if no sound is selected (when sum of probabilities < 1.0).
        """
        total_probability = sum(sound.probability for sound in sounds)
        if total_probability <= 0:
            return None

        if total_probability < 1.0 and random.random() > total_probability:
            return None

        normalize_factor = 1.0 if total_probability <= 1.0 else total_probability
        r = random.random() * min(total_probability, 1.0)
        cumulative = 0.0

        for sound in sounds:
            if sound.probability <= 0:
                continue

            norm_prob = sound.probability / normalize_factor
            cumulative += norm_prob

            if r <= cumulative:
                return sound

        return sounds[-1]

    def _normalize_sound_source(
        self, source: AudioSource | AudioConfig | list[AudioConfig] | None
    ) -> tuple[AudioSource, float] | None:
        if source is None:
            return None

        if isinstance(source, BuiltinAudioClip):
            return self._normalize_builtin_audio(source), 1.0
        elif isinstance(source, list):
            selected = self._select_sound_from_list(source)
            if selected is None:
                return None
            return selected.source, selected.volume
        elif isinstance(source, AudioConfig):
            return self._normalize_builtin_audio(source.source), source.volume

        return source, 1.0

    def _normalize_builtin_audio(self, source: AudioSource) -> AsyncIterator[rtc.AudioFrame] | str:
        if isinstance(source, BuiltinAudioClip):
            return source.path()
        else:
            return source

    def play(
        self,
        audio: AudioSource | AudioConfig | list[AudioConfig],
        *,
        loop: bool = False,
    ) -> PlayHandle:
        """
        Plays an audio once or in a loop.

        Args:
            audio (Union[AudioSource, AudioConfig, List[AudioConfig]]):
                The audio to play. Can be:
                - A string pointing to a file path
                - An AsyncIterator that yields `rtc.AudioFrame`
                - An AudioConfig object with volume and probability
                - A list of AudioConfig objects, where one will be selected based on probability

                If a string is provided and `loop` is True, the sound will be looped.
                If an AsyncIterator is provided, it is played until exhaustion (and cannot be looped
                automatically).
            loop (bool, optional):
                Whether to loop the audio. Only applicable if `audio` is a string or contains strings.
                Defaults to False.

        Returns:
            PlayHandle: An object representing the playback handle. This can be
            awaited or stopped manually.
        """  # noqa: E501
        if not self._mixer_atask:
            raise RuntimeError("BackgroundAudio is not started")

        normalized = self._normalize_sound_source(audio)
        if normalized is None:
            play_handle = PlayHandle()
            play_handle._mark_playout_done()
            return play_handle

        sound_source, volume = normalized

        if loop and isinstance(sound_source, AsyncIterator):
            raise ValueError(
                "Looping sound via AsyncIterator is not supported. Use a string file path or your own 'infinite' AsyncIterator with loop=False"  # noqa: E501
            )

        play_handle = PlayHandle()
        task = asyncio.create_task(self._play_task(play_handle, sound_source, volume, loop))
        task.add_done_callback(lambda _: self._play_tasks.remove(task))
        task.add_done_callback(lambda _: play_handle._mark_playout_done())
        self._play_tasks.append(task)
        return play_handle

    async def start(
        self,
        *,
        room: rtc.Room,
        agent_session: NotGivenOr[AgentSession] = NOT_GIVEN,
        track_publish_options: NotGivenOr[rtc.TrackPublishOptions] = NOT_GIVEN,
    ) -> None:
        """
        Starts the background audio system, publishing the audio track
        and beginning playback of any configured ambient sound.

        If `ambient_sound` is provided (and contains file paths), they will loop
        automatically. If `ambient_sound` contains AsyncIterators, they are assumed
        to be already infinite or looped.

        Args:
            room (rtc.Room):
                The LiveKit Room object where the audio track will be published.
            agent_session (NotGivenOr[AgentSession], optional):
                The session object used to track the agent's state (e.g., "thinking").
                Required if `thinking_sound` is provided.
            track_publish_options (NotGivenOr[rtc.TrackPublishOptions], optional):
                Options used when publishing the audio track. If not given, defaults will
                be used.
        """
        async with self._lock:
            self._room = room
            self._agent_session = agent_session or None
            self._track_publish_options = track_publish_options or None

            try:
                job_ctx = get_job_context()
                if job_ctx.is_fake_job():
                    logger.warning(
                        "Background audio is not supported in console mode. Audio will not be played."
                    )
            except RuntimeError:
                pass

            await self._publish_track()

            self._mixer_atask = asyncio.create_task(self._run_mixer_task())
            self._room.on("reconnected", self._on_reconnected)

            if self._agent_session:
                self._agent_session.on("agent_state_changed", self._agent_state_changed)

            if self._ambient_sound:
                normalized = self._normalize_sound_source(self._ambient_sound)
                if normalized:
                    sound_source, volume = normalized
                    selected_sound = AudioConfig(sound_source, volume)
                    if isinstance(sound_source, str):
                        self._ambient_handle = self.play(selected_sound, loop=True)
                    else:
                        self._ambient_handle = self.play(selected_sound)

    async def aclose(self) -> None:
        """
        Gracefully closes the background audio system, canceling all ongoing
        playback tasks and unpublishing the audio track.
        """
        async with self._lock:
            if not self._mixer_atask:
                return  # not started

            await cancel_and_wait(*self._play_tasks)

            if self._republish_task:
                await cancel_and_wait(self._republish_task)

            await cancel_and_wait(self._mixer_atask)
            self._mixer_atask = None

            await self._audio_mixer.aclose()
            await self._audio_source.aclose()

            if self._agent_session:
                self._agent_session.off("agent_state_changed", self._agent_state_changed)

            self._room.off("reconnected", self._on_reconnected)

            with contextlib.suppress(Exception):
                if self.publication is not None:
                    await self._room.local_participant.unpublish_track(self.publication.sid)

    def _on_reconnected(self) -> None:
        if self._republish_task:
            self._republish_task.cancel()

        self.publication = None
        self._republish_task = asyncio.create_task(self._republish_track_task())

    def _agent_state_changed(self, ev: AgentStateChangedEvent) -> None:
        if not self._thinking_sound:
            return

        if ev.new_state == "thinking":
            if self._thinking_handle and not self._thinking_handle.done():
                return

            assert self._thinking_sound is not None
            self._thinking_handle = self.play(self._thinking_sound)

        elif self._thinking_handle:
            self._thinking_handle.stop()

    @log_exceptions(logger=logger)
    async def _play_task(
        self, play_handle: PlayHandle, sound: AudioSource, volume: float, loop: bool
    ) -> None:
        if isinstance(sound, BuiltinAudioClip):
            sound = sound.path()

        if isinstance(sound, str):
            if loop:
                sound = _loop_audio_frames(sound)
            else:
                sound = audio_frames_from_file(sound)

        stopped = False

        async def _gen_wrapper() -> AsyncGenerator[rtc.AudioFrame, None]:
            async for frame in sound:
                if stopped:
                    break

                if volume != 1.0:
                    data = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32)
                    data *= 10 ** (np.log10(volume))
                    np.clip(data, -32768, 32767, out=data)
                    yield rtc.AudioFrame(
                        data=data.astype(np.int16).tobytes(),
                        sample_rate=frame.sample_rate,
                        num_channels=frame.num_channels,
                        samples_per_channel=frame.samples_per_channel,
                    )
                else:
                    yield frame

            # TODO(theomonnom): the wait_for_playout() may be innaccurate by 400ms
            play_handle._mark_playout_done()

        gen = _gen_wrapper()
        try:
            self._audio_mixer.add_stream(gen)
            await play_handle.wait_for_playout()  # wait for playout or interruption
        finally:
            self._audio_mixer.remove_stream(gen)
            play_handle._mark_playout_done()

            await asyncio.sleep(0)
            if play_handle._stop_fut.done():
                stopped = True
                with contextlib.suppress(RuntimeError):
                    # ignore error caused by race condition between aclose() and gen.__anext__()
                    await gen.aclose()

    @log_exceptions(logger=logger)
    async def _run_mixer_task(self) -> None:
        async for frame in self._audio_mixer:
            await self._audio_source.capture_frame(frame)

    async def _publish_track(self) -> None:
        if self.publication is not None:
            return

        track = rtc.LocalAudioTrack.create_audio_track("background_audio", self._audio_source)
        self.publication = await self._room.local_participant.publish_track(
            track, self._track_publish_options or rtc.TrackPublishOptions()
        )

    @log_exceptions(logger=logger)
    async def _republish_track_task(self) -> None:
        # used to republish the track on agent reconnect
        async with self._lock:
            await self._publish_track()
