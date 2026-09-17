import React from 'react';
import { Shield, Radio, Activity, Cpu, Network } from 'lucide-react';

interface TopNavProps {
  connectionStatus: 'CONNECTED' | 'DISCONNECTED' | 'CONNECTING';
  latencyMs: number;
  modelVersion: string;
  policyVersion: string;
  isStreaming: boolean;
}

export const TopNav: React.FC<TopNavProps> = ({
  connectionStatus,
  latencyMs,
  modelVersion,
  policyVersion,
  isStreaming,
}) => {
  return (
    <header className="w-full bg-slate-950/80 backdrop-blur border-b border-cyan-950/60 px-6 py-3.5 flex flex-wrap items-center justify-between gap-4 sticky top-0 z-50">
      {/* Brand & SOC Identity */}
      <div className="flex items-center gap-3.5">
        <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-600/30 border border-cyan-500/40 flex items-center justify-center shadow-[0_0_15px_rgba(6,182,212,0.25)]">
          <Shield className="w-5 h-5 text-cyan-400 animate-pulse" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-black tracking-wider text-white flex items-center gap-1.5 font-mono">
              VIGIL-AI
            </h1>
            <span className="text-[10px] uppercase font-bold tracking-widest px-2 py-0.5 rounded-full bg-cyan-950/80 text-cyan-300 border border-cyan-800/60">
              SOC LIVE
            </span>
          </div>
          <p className="text-[11px] font-mono tracking-widest text-slate-400 uppercase">
            REAL-TIME VOICE SECURITY OPERATIONS CENTER
          </p>
        </div>
      </div>

      {/* Center Metadata Telemetry */}
      <div className="hidden lg:flex items-center gap-6 px-4 py-1.5 rounded-md bg-slate-900/60 border border-slate-800 text-xs font-mono text-slate-400">
        <div className="flex items-center gap-2">
          <Cpu className="w-3.5 h-3.5 text-purple-400" />
          <span>POLICY: <strong className="text-purple-300 font-semibold">{policyVersion}</strong></span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-blue-400" />
          <span>MODEL: <strong className="text-slate-200 font-semibold">{modelVersion}</strong></span>
        </div>
        <div className="h-3 w-px bg-slate-800" />
        <div className="flex items-center gap-2">
          <Network className="w-3.5 h-3.5 text-emerald-400" />
          <span>LATENCY: <strong className="text-emerald-300 font-semibold">{latencyMs > 0 ? `${latencyMs} ms` : '-- ms'}</strong></span>
        </div>
      </div>

      {/* Connection & Live Stream Badges */}
      <div className="flex items-center gap-3 font-mono text-xs">
        {/* Stream Recording/Live indicator */}
        <div className={`flex items-center gap-2 px-3 py-1 rounded-full border transition-all ${
          isStreaming 
            ? 'bg-rose-950/40 border-rose-600/50 text-rose-300 shadow-[0_0_10px_rgba(244,63,94,0.3)]' 
            : 'bg-slate-900/50 border-slate-800 text-slate-500'
        }`}>
          <span className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-rose-500 animate-ping' : 'bg-slate-600'}`} />
          <span className="font-semibold text-[11px] tracking-wider">
            {isStreaming ? 'STREAM ACTIVE' : 'STREAM STANDBY'}
          </span>
        </div>

        {/* WebSocket Connection Badge */}
        <div className={`flex items-center gap-2 px-3 py-1 rounded-full border transition-all ${
          connectionStatus === 'CONNECTED'
            ? 'bg-emerald-950/40 border-emerald-500/50 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.25)]'
            : connectionStatus === 'CONNECTING'
            ? 'bg-amber-950/40 border-amber-500/50 text-amber-300'
            : 'bg-rose-950/40 border-rose-500/50 text-rose-300'
        }`}>
          <Radio className={`w-3 h-3 ${connectionStatus === 'CONNECTED' ? 'text-emerald-400 animate-pulse' : 'text-slate-400'}`} />
          <span className="font-semibold text-[11px] tracking-wider">{connectionStatus}</span>
        </div>
      </div>
    </header>
  );
};
