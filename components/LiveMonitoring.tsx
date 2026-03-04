import React, { useState, useEffect, useRef } from 'react';
import {
    Activity,
    X,
    Play,
    Square,
    MessageSquare,
    Volume2,
    VolumeX,
    Users,
    Wifi,
    RefreshCw,
    Shield
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
    Room,
    RoomEvent,
    RemoteParticipant,
    RemoteTrack,
    Track,
    TranscriptionSegment
} from 'livekit-client';

const API_URL = import.meta.env.VITE_API_URL || '';

interface LiveSession {
    sid: string;
    name: string;
    num_participants: number;
    created_at: number;
}

interface TranscriptEntry {
    speaker: string;
    text: string;
    timestamp: number;
}

export const LiveMonitoring: React.FC = () => {
    const { t } = useTranslation();
    const [sessions, setSessions] = useState<LiveSession[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [selectedRoom, setSelectedRoom] = useState<string | null>(null);
    const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
    const [isMonitoring, setIsMonitoring] = useState(false);
    const [isMuted, setIsMuted] = useState(true);

    const roomRef = useRef<Room | null>(null);
    const transcriptsEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        loadSessions();
        const interval = setInterval(loadSessions, 30000); // 30s refresh
        return () => {
            clearInterval(interval);
            stopMonitoring();
        };
    }, []);

    useEffect(() => {
        if (transcriptsEndRef.current) {
            transcriptsEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [transcripts]);

    const loadSessions = async () => {
        try {
            setIsLoading(true);
            const res = await fetch(`${API_URL}/api/dashboard/live-sessions`);
            if (res.ok) {
                const data = await res.json();
                setSessions(data);
            }
        } catch (error) {
            console.error('Error loading live sessions:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const startMonitoring = async (roomName: string) => {
        if (isMonitoring) await stopMonitoring();

        try {
            setSelectedRoom(roomName);
            setTranscripts([]);
            setIsMonitoring(true);

            // 1. Get Token
            const tokenRes = await fetch(`${API_URL}/api/dashboard/token?room_name=${roomName}`);
            if (!tokenRes.ok) throw new Error('Failed to get monitoring token');
            const { token } = await tokenRes.json();

            // 2. Connect to LiveKit
            const room = new Room({
                adaptiveStream: true,
                dynacast: true,
            });
            roomRef.current = room;

            // Handle Transcriptions if available via data messages or transcription events
            room.on(RoomEvent.TranscriptionReceived, (segments: TranscriptionSegment[], participant?: RemoteParticipant) => {
                const speaker = participant?.identity || participant?.name || 'Unknown';
                const text = segments.map(s => s.text).join(' ');

                setTranscripts(prev => [
                    ...prev,
                    { speaker, text, timestamp: Date.now() }
                ].slice(-50)); // Keep last 50
            });

            // Handle direct data messages (fallback)
            room.on(RoomEvent.DataReceived, (payload: Uint8Array, participant?: RemoteParticipant) => {
                try {
                    const decoder = new TextDecoder();
                    const data = JSON.parse(decoder.decode(payload));
                    if (data.text || data.transcription) {
                        const speaker = participant?.identity || participant?.name || 'Agent';
                        const text = data.text || data.transcription;
                        setTranscripts(prev => [
                            ...prev,
                            { speaker, text, timestamp: Date.now() }
                        ].slice(-50));
                    }
                } catch (e) {
                    // Not a JSON message or transcript
                }
            });

            // Handle remote tracks (audio)
            room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
                if (track.kind === Track.Kind.Audio) {
                    track.attach();
                }
            });

            const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || 'wss://ausarta-robot-m7e6v2y5.livekit.cloud';
            await room.connect(LIVEKIT_URL, token);
            console.log('Connected to room for monitoring:', roomName);

        } catch (error) {
            console.error('Monitoring error:', error);
            setIsMonitoring(false);
            setSelectedRoom(null);
        }
    };

    const stopMonitoring = async () => {
        if (roomRef.current) {
            await roomRef.current.disconnect();
            roomRef.current = null;
        }
        setIsMonitoring(false);
        setSelectedRoom(null);
        setTranscripts([]);
    };

    const toggleAudio = () => {
        if (!roomRef.current) return;

        setIsMuted(!isMuted);
        roomRef.current.remoteParticipants.forEach(p => {
            p.audioTrackPublications.forEach(pub => {
                if (pub.track) {
                    if (isMuted) (pub.track as any).unmute(); // This is internal
                    else (pub.track as any).mute();
                }
            });
        });
    };

    return (
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-100 dark:border-gray-700 shadow-sm overflow-hidden animate-slide-up h-full flex flex-col">
            <div className="p-4 border-b border-gray-50 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-700/30 flex justify-between items-center">
                <div className="flex items-center gap-2">
                    <Shield className="text-blue-600" size={20} />
                    <h3 className="font-bold text-gray-800 dark:text-white">
                        {t('Live Supervision', 'Supervisión en Vivo')}
                    </h3>
                </div>
                <button
                    onClick={loadSessions}
                    className="p-1.5 hover:bg-white dark:hover:bg-gray-600 rounded-lg transition-colors"
                >
                    <RefreshCw size={14} className={`${isLoading ? 'animate-spin' : 'text-gray-400'}`} />
                </button>
            </div>

            <div className="flex-1 flex flex-col min-h-[300px]">
                {!isMonitoring ? (
                    <div className="p-4 flex-1 overflow-y-auto">
                        <div className="space-y-2">
                            {sessions.length === 0 ? (
                                <div className="text-center py-12">
                                    <div className="w-12 h-12 bg-gray-50 dark:bg-gray-700 rounded-full flex items-center justify-center mx-auto mb-3">
                                        <Activity size={24} className="text-gray-300" />
                                    </div>
                                    <p className="text-sm text-gray-500">{t('No active calls at the moment', 'No hay llamadas activas')}</p>
                                </div>
                            ) : (
                                sessions.map(session => (
                                    <div
                                        key={session.sid}
                                        className="group p-3 border border-gray-100 dark:border-gray-700 rounded-xl hover:bg-blue-50/50 dark:hover:bg-blue-900/10 transition-all flex items-center justify-between"
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                                            <div>
                                                <p className="text-sm font-bold text-gray-800 dark:text-white">{session.name}</p>
                                                <p className="text-[10px] text-gray-500 flex items-center gap-1">
                                                    <Users size={10} /> {session.num_participants} {t('participants')}
                                                </p>
                                            </div>
                                        </div>
                                        <button
                                            onClick={() => startMonitoring(session.name)}
                                            className="px-3 py-1.5 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-lg text-[10px] font-bold opacity-0 group-hover:opacity-100 transition-all"
                                        >
                                            {t('Monitor', 'Monitorear')}
                                        </button>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="flex-1 flex flex-col overflow-hidden bg-gray-900 text-white">
                        <div className="p-3 border-b border-white/10 flex justify-between items-center bg-gray-900/50 backdrop-blur-md">
                            <div className="flex items-center gap-2">
                                <span className="flex h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                                <span className="text-xs font-bold uppercase tracking-wider">{selectedRoom}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={() => setIsMuted(!isMuted)}
                                    className={`p-1.5 rounded-lg transition-colors ${isMuted ? 'text-gray-400 hover:text-white' : 'text-blue-400 hover:text-blue-300'}`}
                                >
                                    {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
                                </button>
                                <button
                                    onClick={stopMonitoring}
                                    className="p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-500 rounded-lg transition-colors"
                                >
                                    <Square size={16} fill="currentColor" />
                                </button>
                            </div>
                        </div>

                        <div className="flex-1 p-4 overflow-y-auto space-y-4 font-mono text-xs">
                            {transcripts.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-gray-500 space-y-2">
                                    <MessageSquare size={32} />
                                    <p>{t('Waiting for transcription...', 'Esperando transcripción...')}</p>
                                </div>
                            ) : (
                                transcripts.map((t, i) => (
                                    <div key={i} className="animate-fade-in">
                                        <span className={`font-bold mr-2 ${t.speaker.toLowerCase().includes('agent') ? 'text-blue-400' : 'text-green-400'}`}>
                                            [{t.speaker}]:
                                        </span>
                                        <span className="text-gray-300">{t.text}</span>
                                    </div>
                                ))
                            )}
                            <div ref={transcriptsEndRef} />
                        </div>
                    </div>
                )}
            </div>

            <div className="p-3 bg-gray-50 dark:bg-gray-700/30 text-[10px] text-gray-500 flex items-center justify-between border-t border-gray-100 dark:border-gray-700">
                <span className="flex items-center gap-1"><Wifi size={10} /> LiveKit Cloud</span>
                <span>{sessions.length} {t('Active Rooms', 'Salas Activas')}</span>
            </div>
        </div>
    );
};
