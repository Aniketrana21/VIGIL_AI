import React, { useEffect, useRef } from 'react';
import { Mic, Radio } from 'lucide-react';

interface CenterPanelProps {
  callStatus: 'MONITORING' | 'CHALLENGING' | 'WARNED' | 'BLOCKED';
  voiceAuthenticity: number;
  speakerMatch: number;
  liveness: number;
  deepfakeProbability: number;
  riskScore: number;
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  action: 'ALLOW' | 'MONITOR' | 'CHALLENGE' | 'WARN' | 'BLOCK';
  confidence: number;
  vadActive: boolean;
  isStreaming: boolean;
  onToggleStream: () => void;
  audioAnalyser?: AnalyserNode | null;
  waveformSample?: number[];
  explanation?: string;
  callerTranscript?: string;
}

// Generate ASCII bar block (e.g. ████████████░ 91%)
function renderAsciiBar(value: number, length: number = 14): string {
  const clamped = Math.max(0, Math.min(100, value));
  const filledCount = Math.round((clamped / 100) * length);
  const emptyCount = length - filledCount;
  return '█'.repeat(filledCount) + '░'.repeat(emptyCount);
}

export const CenterPanel: React.FC<CenterPanelProps> = ({
  callStatus,
  voiceAuthenticity,
  speakerMatch,
  liveness,
  deepfakeProbability,
  riskScore,
  riskLevel,
  action,
  confidence,
  vadActive,
  isStreaming,
  onToggleStream,
  audioAnalyser,
  waveformSample,
  explanation,
  callerTranscript,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Live Oscilloscope Waveform Drawer
  useEffect(() => {
    let animationFrameId: number;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let dummyPhase = 0;

    const render = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      // Grid background
      ctx.strokeStyle = 'rgba(30, 58, 102, 0.25)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x < width; x += 30) {
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
      }
      for (let y = 0; y < height; y += 20) {
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
      }
      ctx.stroke();

      // Center baseline
      ctx.strokeStyle = 'rgba(6, 182, 212, 0.2)';
      ctx.beginPath();
      ctx.moveTo(0, height / 2);
      ctx.lineTo(width, height / 2);
      ctx.stroke();

      // Draw real or simulated waveform
      ctx.lineWidth = 2;
      if (waveformSample && waveformSample.length > 0) {
        ctx.strokeStyle = '#06b6d4';
        ctx.beginPath();
        const sliceWidth = width / waveformSample.length;
        let x = 0;
        for (let i = 0; i < waveformSample.length; i++) {
          const v = waveformSample[i];
          const y = height / 2 - v * (height * 0.45);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
          x += sliceWidth;
        }
        ctx.stroke();
      } else if (audioAnalyser) {
        const bufferLength = audioAnalyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        audioAnalyser.getByteTimeDomainData(dataArray);

        ctx.strokeStyle = '#06b6d4';
        ctx.beginPath();
        const sliceWidth = width / bufferLength;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
          const v = dataArray[i] / 128.0;
          const y = (v * height) / 2;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
          x += sliceWidth;
        }
        ctx.stroke();
      } else {
        // Simulated ambient pulse or idle wave
        dummyPhase += isStreaming ? 0.08 : 0.02;
        ctx.strokeStyle = isStreaming ? (vadActive ? '#10b981' : '#06b6d4') : '#475569';
        ctx.beginPath();
        for (let x = 0; x < width; x++) {
          const amp = isStreaming ? (vadActive ? 24 : 10) : 3;
          const y = height / 2 + Math.sin(x * 0.03 + dummyPhase) * amp * Math.cos(x * 0.01);
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animationFrameId);
  }, [audioAnalyser, isStreaming, vadActive, waveformSample]);

  // Risk Color Helper
  const getRiskColor = (score: number) => {
    if (score >= 85) return 'text-rose-500';
    if (score >= 60) return 'text-amber-400';
    if (score >= 35) return 'text-cyan-400';
    return 'text-emerald-400';
  };

  const getRiskBorder = (score: number) => {
    if (score >= 85) return 'border-rose-500/40 shadow-[0_0_20px_rgba(244,63,94,0.2)]';
    if (score >= 60) return 'border-amber-500/40 shadow-[0_0_20px_rgba(245,158,11,0.2)]';
    if (score >= 35) return 'border-cyan-500/40 shadow-[0_0_15px_rgba(6,182,212,0.15)]';
    return 'border-emerald-500/40 shadow-[0_0_15px_rgba(16,185,129,0.15)]';
  };

  return (
    <section className="flex-1 flex flex-col gap-5 p-6 bg-slate-950/40 rounded-2xl border border-slate-800/80 backdrop-blur-md">
      
      {/* CALL STATUS HEADER */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800/80">
        <div>
          <span className="text-[11px] font-mono uppercase tracking-widest text-slate-400 font-semibold block mb-1">
            CALL STATUS
          </span>
          <div className="flex items-center gap-3">
            <span className="flex h-3.5 w-3.5 relative">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                callStatus === 'BLOCKED' ? 'bg-rose-500' : callStatus === 'CHALLENGING' ? 'bg-amber-400' : 'bg-emerald-400'
              }`} />
              <span className={`relative inline-flex rounded-full h-3.5 w-3.5 ${
                callStatus === 'BLOCKED' ? 'bg-rose-500' : callStatus === 'CHALLENGING' ? 'bg-amber-500' : 'bg-emerald-500'
              }`} />
            </span>
            <span className="text-xl font-black font-mono tracking-wider text-white">
              {callStatus}
            </span>
          </div>
        </div>

        {/* Streaming Mic Control */}
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleStream}
            className={`px-4 py-2 rounded-lg font-mono text-xs font-bold tracking-wider flex items-center gap-2 border transition-all cursor-pointer ${
              isStreaming
                ? 'bg-rose-500/20 border-rose-500/50 text-rose-300 hover:bg-rose-500/30'
                : 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300 hover:bg-cyan-500/30 shadow-[0_0_15px_rgba(6,182,212,0.2)]'
            }`}
          >
            <Mic className="w-4 h-4" />
            <span>{isStreaming ? 'STOP MICROPHONE' : 'START MICROPHONE'}</span>
          </button>
        </div>
      </div>

      {/* CORE SOC GAUGES (VOICE AUTHENTICITY, SPEAKER MATCH, LIVENESS, DEEPFAKE, RISK) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono">
        
        {/* Voice Authenticity */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 mb-2">
            <span className="tracking-wider font-semibold">VOICE AUTHENTICITY</span>
            <span className="text-emerald-400 font-bold">{voiceAuthenticity}%</span>
          </div>
          <div className="text-sm text-emerald-400 tracking-tighter whitespace-pre select-none font-bold">
            {renderAsciiBar(voiceAuthenticity, 14)} <span className="text-white text-xs">{voiceAuthenticity}%</span>
          </div>
          <div className="w-full bg-slate-800/80 h-1.5 rounded-full mt-3 overflow-hidden">
            <div 
              className="bg-emerald-400 h-full rounded-full transition-all duration-300"
              style={{ width: `${voiceAuthenticity}%` }}
            />
          </div>
        </div>

        {/* Speaker Match */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 mb-2">
            <span className="tracking-wider font-semibold">SPEAKER MATCH</span>
            <span className="text-cyan-400 font-bold">{speakerMatch}%</span>
          </div>
          <div className="text-sm text-cyan-400 tracking-tighter whitespace-pre select-none font-bold">
            {renderAsciiBar(speakerMatch, 14)} <span className="text-white text-xs">{speakerMatch}%</span>
          </div>
          <div className="w-full bg-slate-800/80 h-1.5 rounded-full mt-3 overflow-hidden">
            <div 
              className="bg-cyan-400 h-full rounded-full transition-all duration-300"
              style={{ width: `${speakerMatch}%` }}
            />
          </div>
        </div>

        {/* Liveness */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 mb-2">
            <span className="tracking-wider font-semibold">LIVENESS</span>
            <span className="text-amber-400 font-bold">{liveness}%</span>
          </div>
          <div className="text-sm text-amber-400 tracking-tighter whitespace-pre select-none font-bold">
            {renderAsciiBar(liveness, 14)} <span className="text-white text-xs">{liveness}%</span>
          </div>
          <div className="w-full bg-slate-800/80 h-1.5 rounded-full mt-3 overflow-hidden">
            <div 
              className="bg-amber-400 h-full rounded-full transition-all duration-300"
              style={{ width: `${liveness}%` }}
            />
          </div>
        </div>

        {/* Deepfake Probability */}
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex flex-col justify-between">
          <div className="flex justify-between items-center text-xs text-slate-400 mb-2">
            <span className="tracking-wider font-semibold">DEEPFAKE PROBABILITY</span>
            <span className="text-rose-400 font-bold">{deepfakeProbability}%</span>
          </div>
          <div className="text-sm text-rose-400 tracking-tighter whitespace-pre select-none font-bold">
            {renderAsciiBar(deepfakeProbability, 14)} <span className="text-white text-xs">{deepfakeProbability}%</span>
          </div>
          <div className="w-full bg-slate-800/80 h-1.5 rounded-full mt-3 overflow-hidden">
            <div 
              className="bg-rose-500 h-full rounded-full transition-all duration-300"
              style={{ width: `${deepfakeProbability}%` }}
            />
          </div>
        </div>

      </div>

      {/* OVERALL RISK SCORE BANNER */}
      <div className={`p-5 rounded-xl bg-slate-900/90 border flex flex-wrap items-center justify-between gap-4 font-mono ${getRiskBorder(riskScore)}`}>
        <div>
          <span className="text-xs uppercase tracking-widest text-slate-400 font-semibold block mb-1">
            RISK ASSESSMENT
          </span>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-black tracking-tight text-white flex items-center gap-2">
              <span className={getRiskColor(riskScore)}>●</span> {riskScore}
              <span className="text-sm font-normal text-slate-500">/ 100</span>
            </span>
            <span className={`px-2.5 py-0.5 rounded text-xs font-bold uppercase tracking-wider ${
              riskLevel === 'CRITICAL' ? 'bg-rose-950 text-rose-300 border border-rose-800' :
              riskLevel === 'HIGH' ? 'bg-amber-950 text-amber-300 border border-amber-800' :
              riskLevel === 'MEDIUM' ? 'bg-cyan-950 text-cyan-300 border border-cyan-800' :
              'bg-emerald-950 text-emerald-300 border border-emerald-800'
            }`}>
              {riskLevel} RISK
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs">
          <div className="text-right">
            <span className="text-slate-400 block text-[11px]">RECOMMENDED ACTION</span>
            <span className={`font-bold tracking-wider text-sm ${
              action === 'BLOCK' ? 'text-rose-400' : action === 'WARN' ? 'text-amber-400' : action === 'CHALLENGE' ? 'text-purple-400' : 'text-emerald-400'
            }`}>
              {action}
            </span>
          </div>
          <div className="h-8 w-px bg-slate-800" />
          <div className="text-right">
            <span className="text-slate-400 block text-[11px]">CONFIDENCE</span>
            <span className="font-bold text-slate-200 text-sm">{Math.round(confidence * 100)}%</span>
          </div>
        </div>
      </div>

      {/* CALLER SPEECH REAL-TIME TRANSCRIPTION DISPLAY */}
      <div className="rounded-xl bg-slate-900/90 border border-cyan-500/30 p-4 font-mono text-xs shadow-lg">
        <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <span className="text-base">🎙️</span>
            <span className="text-xs font-mono font-bold tracking-wider uppercase text-cyan-300">
              Caller Speech Real-Time Transcription
            </span>
          </div>
          <div className="flex items-center gap-2">
            {callerTranscript && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800 animate-pulse">
                💾 AUTO-STORED IN DB
              </span>
            )}
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">
              WHISPER &amp; STT
            </span>
          </div>
        </div>

        <div className="p-3.5 rounded-lg bg-black/60 border border-slate-800/80 min-h-[52px] flex items-center">
          {callerTranscript ? (
            <div className="space-y-1">
              <div className="text-[10px] uppercase tracking-wider text-cyan-400 font-bold">
                Spoken Phrase (Transcribed):
              </div>
              <p className="text-white text-sm font-semibold leading-relaxed">
                "{callerTranscript}"
              </p>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-slate-500 italic text-xs">
              <span className="w-2 h-2 rounded-full bg-slate-600 animate-ping" />
              <span>Start microphone and speak, or run a demo scenario — spoken caller text will appear here and evaluate in real time.</span>
            </div>
          )}
        </div>
      </div>

      {/* LIVE WAVEFORM OSCILLOSCOPE */}
      <div className="relative rounded-xl overflow-hidden bg-slate-950 border border-slate-800 flex-1 min-h-[140px] flex flex-col justify-end">
        <div className="absolute top-3 left-4 flex items-center gap-2 z-10">
          <Radio className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
          <span className="text-[11px] font-mono tracking-widest text-slate-400 uppercase font-semibold">
            LIVE OSCILLOSCOPE &amp; VAD
          </span>
        </div>

        <div className="absolute top-3 right-4 z-10 flex items-center gap-2">
          <span className={`flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono border ${
            vadActive
              ? 'bg-emerald-950/60 border-emerald-500/50 text-emerald-300'
              : 'bg-slate-900/80 border-slate-800 text-slate-400'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${vadActive ? 'bg-emerald-400 animate-ping' : 'bg-slate-500'}`} />
            <span>{vadActive ? 'VAD: SPEECH DETECTED' : 'VAD: IDLE / SILENCE'}</span>
          </span>
        </div>

        <canvas
          ref={canvasRef}
          width={700}
          height={140}
          className="w-full h-[140px] block"
        />
      </div>

      {/* EXPLANATION / REASONING CARD */}
      {explanation && (
        <div className="rounded-xl bg-slate-950/90 border border-slate-800 p-4 font-mono text-xs text-slate-300 shadow-inner">
          <div className="flex items-center gap-2 text-cyan-400 font-bold mb-1.5 uppercase text-[11px] tracking-wider">
            <span>🛡️</span>
            <span>Multi-Factor Risk Engine Explanation</span>
          </div>
          <div className="whitespace-pre-line leading-relaxed text-slate-300 text-[11px] bg-slate-900/60 p-2.5 rounded border border-slate-800/80">
            {explanation}
          </div>
        </div>
      )}

    </section>
  );
};
