import React from 'react';
import { Shield, Radio, Activity, Cpu, Network, Database, Phone } from 'lucide-react';
import { isSupabaseConfigured } from '../lib/supabase';

interface TopNavProps {
  connectionStatus: 'CONNECTED' | 'DISCONNECTED' | 'CONNECTING';
  latencyMs: number;
  modelVersion: string;
  policyVersion: string;
  isStreaming: boolean;
  onOpenIncomingCallScreen?: () => void;
  onTriggerLiveFraudCall?: () => void;
  latestCall?: {
    action: string;
    risk_score: number;
    caller_name: string;
  } | null;
}

export const TopNav: React.FC<TopNavProps> = ({
  connectionStatus,
  latencyMs,
  modelVersion,
  policyVersion,
  isStreaming,
  onOpenIncomingCallScreen,
  onTriggerLiveFraudCall,
  latestCall,
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

        {/* Supabase Cloud DB Badge */}
        <div className={`hidden sm:flex items-center gap-1.5 px-3 py-1 rounded-full border transition-all ${
          isSupabaseConfigured
            ? 'bg-cyan-950/40 border-cyan-500/40 text-cyan-300 shadow-[0_0_10px_rgba(6,182,212,0.2)]'
            : 'bg-slate-900/50 border-slate-800 text-slate-500'
        }`} title="Supabase Cloud Realtime DB">
          <Database className="w-3 h-3 text-cyan-400" />
          <span className="font-semibold text-[11px] tracking-wider">SUPABASE CLOUD</span>
        </div>

        {/* WebSocket Connection Badge */}
        <div className={`flex items-center gap-2 px-3 py-1 rounded-full border transition-all ${
          connectionStatus === 'CONNECTED'
            ? 'bg-emerald-950/40 border-emerald-500/50 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.25)]'
            : connectionStatus === 'CONNECTING'
            ? 'bg-amber-950/40 border-amber-500/50 text-amber-300'
            : 'bg-rose-950/40 border-rose-500/50 text-rose-300 shadow-[0_0_10px_rgba(244,63,94,0.3)]'
        }`}>
          <Radio className={`w-3 h-3 ${connectionStatus === 'CONNECTED' ? 'text-emerald-400 animate-pulse' : 'text-slate-400'}`} />
          <span className="font-semibold text-[11px] tracking-wider">{connectionStatus}</span>
        </div>

        {/* Dynamic Test Fraud Trigger */}
        {onTriggerLiveFraudCall && (
          <button
            onClick={onTriggerLiveFraudCall}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full font-mono text-[11px] font-bold bg-rose-600/90 hover:bg-rose-500 text-white shadow-[0_0_15px_rgba(244,63,94,0.35)] border border-rose-400 transition-all active:scale-95 cursor-pointer"
            title="Simulate immediate live fraud call to test real-time defense pipeline"
          >
            <Shield className="w-3.5 h-3.5 text-rose-200" />
            <span className="hidden sm:inline">SIMULATE FRAUD CALL</span>
            <span className="sm:hidden">TEST FRAUD</span>
          </button>
        )}

        {/* Incoming Call Screen Launcher */}
        {onOpenIncomingCallScreen && (
          <button
            onClick={onOpenIncomingCallScreen}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full font-mono text-[11px] font-bold shadow-lg border transition-all active:scale-95 cursor-pointer ${
              latestCall?.action === 'BLOCK'
                ? 'bg-rose-950/80 border-rose-500 text-rose-200 shadow-rose-900/50 animate-pulse'
                : latestCall?.action === 'ALLOW'
                ? 'bg-emerald-950/80 border-emerald-500 text-emerald-200 shadow-emerald-900/40'
                : 'bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white shadow-cyan-900/40 border-cyan-400/40'
            }`}
            title="Open VIGIL-AI Incoming Call Screen (Live Telecom HUD)"
          >
            <Phone className="w-3.5 h-3.5" />
            <span>
              {latestCall ? `INCOMING HUD: ${latestCall.action} (${latestCall.risk_score} pts)` : 'INCOMING CALL HUD'}
            </span>
          </button>
        )}
      </div>

      {/* Network Degradation Banner */}
      {connectionStatus === 'DISCONNECTED' && (
        <div className="w-full bg-amber-950/80 border-t border-amber-600/60 px-6 py-2 flex items-center justify-between text-xs font-mono text-amber-300 animate-pulse">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
            <strong>⚠️ NETWORK DEGRADED / OFFLINE</strong>
            <span className="text-amber-400/80 hidden sm:inline">— Real-time telemetry interrupted. Running in local fallback buffer mode.</span>
          </div>
          <span className="text-[10px] text-amber-400 uppercase tracking-widest">RECONNECTING...</span>
        </div>
      )}
    </header>
  );
};
