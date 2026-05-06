
import React, { useState, useEffect, useRef } from 'react';
import { X, Mic, MicOff, PhoneOff, AudioWaveform } from 'lucide-react';
import { GoogleGenAI, LiveServerMessage, Modality, Blob } from '@google/genai';

interface LiveCallViewProps {
  onClose: () => void;
}

const LiveCallView: React.FC<LiveCallViewProps> = ({ onClose }) => {
  const [isConnecting, setIsConnecting] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [transcript, setTranscript] = useState<string[]>([]);
  const [volume, setVolume] = useState(0);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const outputCtxRef = useRef<AudioContext | null>(null);
  const nextStartTimeRef = useRef(0);
  const sourcesRef = useRef(new Set<AudioBufferSourceNode>());
  const sessionRef = useRef<any>(null);

  useEffect(() => {
    startSession();
    return () => {
      stopSession();
    };
  }, []);

  const decode = (base64: string) => {
    const binaryString = atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
  };

  const decodeAudioData = async (
    data: Uint8Array,
    ctx: AudioContext,
    sampleRate: number,
    numChannels: number,
  ): Promise<AudioBuffer> => {
    const dataInt16 = new Int16Array(data.buffer);
    const frameCount = dataInt16.length / numChannels;
    const buffer = ctx.createBuffer(numChannels, frameCount, sampleRate);

    for (let channel = 0; channel < numChannels; channel++) {
      const channelData = buffer.getChannelData(channel);
      for (let i = 0; i < frameCount; i++) {
        channelData[i] = dataInt16[i * numChannels + channel] / 32768.0;
      }
    }
    return buffer;
  };

  const encode = (bytes: Uint8Array) => {
    let binary = '';
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  };

  const createBlob = (data: Float32Array): Blob => {
    const l = data.length;
    const int16 = new Int16Array(l);
    for (let i = 0; i < l; i++) {
      int16[i] = data[i] * 32768;
    }
    return {
      data: encode(new Uint8Array(int16.buffer)),
      mimeType: 'audio/pcm;rate=16000',
    };
  };

  const startSession = async () => {
    try {
      const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || '' });
      
      const inputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
      const outputAudioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
      audioCtxRef.current = inputAudioContext;
      outputCtxRef.current = outputAudioContext;

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      const sessionPromise = ai.live.connect({
        model: 'gemini-2.5-flash-native-audio-preview-12-2025',
        callbacks: {
          onopen: () => {
            setIsConnecting(false);
            setIsConnected(true);
            
            const source = inputAudioContext.createMediaStreamSource(stream);
            const scriptProcessor = inputAudioContext.createScriptProcessor(4096, 1, 1);
            
            scriptProcessor.onaudioprocess = (e) => {
              if (isMuted) return;
              const inputData = e.inputBuffer.getChannelData(0);
              
              // Simple volume detection for visualizer
              let sum = 0;
              for(let i=0; i<inputData.length; i++) sum += inputData[i] * inputData[i];
              setVolume(Math.sqrt(sum / inputData.length) * 100);

              const pcmBlob = createBlob(inputData);
              sessionPromise.then(session => {
                session.sendRealtimeInput({ media: pcmBlob });
              });
            };
            
            source.connect(scriptProcessor);
            scriptProcessor.connect(inputAudioContext.destination);
          },
          onmessage: async (message: LiveServerMessage) => {
            if (message.serverContent?.outputTranscription) {
              const text = message.serverContent.outputTranscription.text;
              setTranscript(prev => [...prev.slice(-4), `AI: ${text}`]);
            } else if (message.serverContent?.inputTranscription) {
              const text = message.serverContent.inputTranscription.text;
              setTranscript(prev => [...prev.slice(-4), `You: ${text}`]);
            }

            const base64Audio = message.serverContent?.modelTurn?.parts[0]?.inlineData?.data;
            if (base64Audio) {
              nextStartTimeRef.current = Math.max(nextStartTimeRef.current, outputAudioContext.currentTime);
              const audioBuffer = await decodeAudioData(decode(base64Audio), outputAudioContext, 24000, 1);
              const source = outputAudioContext.createBufferSource();
              source.buffer = audioBuffer;
              source.connect(outputAudioContext.destination);
              source.start(nextStartTimeRef.current);
              nextStartTimeRef.current += audioBuffer.duration;
              sourcesRef.current.add(source);
              source.onended = () => sourcesRef.current.delete(source);
            }

            if (message.serverContent?.interrupted) {
              sourcesRef.current.forEach(s => s.stop());
              sourcesRef.current.clear();
              nextStartTimeRef.current = 0;
            }
          },
          onerror: (e) => {
            console.error('Gemini Live error:', e);
            setIsConnecting(false);
          },
          onclose: () => {
            setIsConnected(false);
          }
        },
        config: {
          responseModalities: [Modality.AUDIO],
          speechConfig: {
            voiceConfig: { prebuiltVoiceConfig: { voiceName: 'Kore' } },
          },
          systemInstruction: 'You are an expert AI voice agent for Ausarta Robot. Your goal is to help the user configure their dashboard and explain how voice calls work. Be concise, professional, and friendly. Answer in the user\'s language.',
          inputAudioTranscription: {},
          outputAudioTranscription: {}
        }
      });

      sessionRef.current = await sessionPromise;
    } catch (err) {
      console.error('Failed to start session:', err);
      setIsConnecting(false);
    }
  };

  const stopSession = () => {
    if (sessionRef.current) {
      sessionRef.current.close();
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close();
    }
    if (outputCtxRef.current) {
      outputCtxRef.current.close();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4">
      <div className="bg-slate-900 w-full max-w-md rounded-3xl shadow-[0_0_50px_rgba(0,0,0,0.5)] border border-slate-800 overflow-hidden flex flex-col min-h-[550px]">
        {/* Header */}
        <div className="p-5 flex items-center justify-between border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full shadow-[0_0_10px_rgba(0,0,0,0.5)] ${isConnected ? 'bg-cyan-500 shadow-cyan-500/50 animate-pulse' : 'bg-slate-700'}`} />
            <span className="text-sm font-bold text-slate-200 tracking-wider">CYBER-OPS TERMINAL</span>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-800 rounded-xl transition-all text-slate-400 hover:text-white">
            <X size={20} />
          </button>
        </div>

        {/* Call Body */}
        <div className="flex-1 p-8 flex flex-col items-center justify-center space-y-8">
            {/* Circular Voice Wave - Cyber-Ops Style */}
            <div className="w-48 h-48 rounded-full bg-slate-950/20 backdrop-blur-3xl flex items-center justify-center relative overflow-hidden border border-cyan-500/20 shadow-[0_0_30px_rgba(0,240,255,0.1)] group">
               {isConnected && (
                 <>
                   {/* Expanding pulse waves */}
                   <div className="absolute inset-0 bg-cyan-400/20 rounded-full animate-ping" style={{ animationDuration: '2s', transform: `scale(${1 + volume/100})` }} />
                   <div className="absolute inset-0 bg-cyan-500/10 rounded-full animate-ping" style={{ animationDuration: '3s', transform: `scale(${1.2 + volume/80})` }} />
                   
                   {/* Orbiting particles (simulated with border shadows) */}
                   <div className="absolute inset-0 rounded-full border border-cyan-500/10 animate-[spin_10s_linear_infinite]" />
                   
                   {/* Dynamic Waveform Overlay */}
                   <div className="absolute inset-0 flex items-center justify-center opacity-30">
                     {[...Array(24)].map((_, i) => (
                       <div 
                         key={i}
                         className="w-1 bg-cyan-400 rounded-full mx-[1px] transition-all duration-75"
                         style={{ 
                           height: `${20 + Math.random() * (volume + 10)}%`,
                           opacity: 0.3 + (volume / 100)
                         }}
                       />
                     ))}
                   </div>
                 </>
               )}
               
               {/* Central Icon */}
            </div>

            <div className="text-center">
              <h2 className="text-2xl font-bold text-white tracking-tight drop-shadow-[0_0_10px_rgba(0,240,255,0.3)]">
                {isConnecting ? 'ESTABLISHING SECURE LINK...' : isConnected ? 'OPERATIVE STATUS: ACTIVE' : 'CONNECTION TERMINATED'}
              </h2>
              <p className="text-sm text-cyan-500/60 mt-2 font-mono uppercase tracking-widest">
                {isConnected ? 'Bi-directional voice stream active' : 'Waiting for Gemini uplink...'}
              </p>
            </div>

            {/* Transcript Area */}
            <div className="w-full bg-slate-950/50 rounded-2xl p-5 h-32 overflow-y-auto border border-slate-800/50 scrollbar-hide">
              {transcript.length === 0 ? (
                <p className="text-xs text-slate-600 italic text-center mt-8 font-mono">WAITING FOR DATA PACKETS...</p>
              ) : (
                <div className="space-y-3">
                  {transcript.map((line, idx) => (
                    <p key={idx} className={`text-[11px] font-mono leading-relaxed ${line.startsWith('AI:') ? 'text-cyan-400' : 'text-slate-400'}`}>
                      <span className="opacity-50 mr-2">{'>'}</span>{line}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="p-10 border-t border-slate-800 bg-slate-950/30 flex items-center justify-center gap-8">
            <button 
              onClick={() => setIsMuted(!isMuted)}
              className={`p-5 rounded-2xl shadow-xl transition-all duration-300 border ${isMuted ? 'bg-red-500/10 border-red-500 text-red-500' : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-cyan-400 hover:border-cyan-500/50'}`}
            >
              {isMuted ? <MicOff size={24} /> : <Mic size={24} />}
            </button>
            
            <button 
              onClick={onClose}
              className="p-6 bg-red-600 text-white rounded-2xl shadow-[0_0_20px_rgba(220,38,38,0.4)] hover:bg-red-500 transition-all hover:scale-110 active:scale-95 border border-red-400/30"
            >
              <PhoneOff size={32} />
            </button>
          </div>
        </div>
      </div>
    );
};

export default LiveCallView;
