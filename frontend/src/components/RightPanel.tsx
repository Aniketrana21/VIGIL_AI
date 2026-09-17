import React from 'react';
import { AlertCircle, CheckCircle2, Clock, MessageSquare, ShieldAlert } from 'lucide-react';

interface RightPanelProps {
  threatSignals: string[];
  timeline: Array<{
    id: string;
    time: string;
    verdict: 'Genuine' | 'Suspicious' | 'Synthetic' | 'Critical';
    confidence: number;
    detail: string;
  }>;
  conversation: {
    intent: string;
    risk_signal: number;
    evidence: string;
  } | null;
  activeChallenge?: {
    challenge_id: string;
    prompt: string;
    expires_in_sec: number;
    status: 'PENDING' | 'PASSED' | 'FAILED';
  } | null;
}

export const RightPanel: React.FC<RightPanelProps> = ({
  threatSignals,
  timeline,
  conversation,
  activeChallenge,
}) => {
  const getTimelineBadge = (verdict: 'Genuine' | 'Suspicious' | 'Synthetic' | 'Critical') => {
    switch (verdict) {
      case 'Critical':
        return 'text-rose-400 bg-rose-950/60 border-rose-800';
      case 'Synthetic':
        return 'text-orange-400 bg-orange-950/60 border-orange-800';
      case 'Suspicious':
        return 'text-amber-300 bg-amber-950/60 border-amber-800';
      case 'Genuine':
      default:
        return 'text-emerald-300 bg-emerald-950/60 border-emerald-800';
    }
  };

  return (
    <aside className="w-full lg:w-[380px] flex flex-col gap-5 p-6 bg-slate-950/40 rounded-2xl border border-slate-800/80 backdrop-blur-md">
      
      {/* THREAT SIGNALS CARD */}
      <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-4">
        <div className="flex items-center justify-between pb-2 mb-3 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-rose-400" />
            <span className="text-xs font-mono font-bold tracking-wider uppercase text-slate-200">
              Threat Signals
            </span>
          </div>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">
            {threatSignals.length} Active
          </span>
        </div>

        <ul className="space-y-2 font-mono text-xs">
          {threatSignals.length > 0 ? (
            threatSignals.map((signal, idx) => (
              <li key={idx} className="flex items-start gap-2 text-rose-300 bg-rose-950/20 px-2.5 py-1.5 rounded-md border border-rose-900/40">
                <span className="text-rose-400 font-bold">✓</span>
                <span className="leading-tight">{signal}</span>
              </li>
            ))
          ) : (
            <li className="flex items-center gap-2 text-emerald-400 bg-emerald-950/20 px-2.5 py-1.5 rounded-md border border-emerald-900/40">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>No abnormal threat signals detected (nominal)</span>
            </li>
          )}
        </ul>
      </div>

      {/* SECURITY EVENT TIMELINE */}
      <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-4 flex-1 flex flex-col">
        <div className="flex items-center justify-between pb-2 mb-3 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-cyan-400" />
            <span className="text-xs font-mono font-bold tracking-wider uppercase text-slate-200">
              Timeline Audit Log
            </span>
          </div>
          <span className="text-[10px] font-mono text-slate-400 uppercase">
            CHRONO BUFFER
          </span>
        </div>

        <div className="space-y-2 overflow-y-auto max-h-[220px] pr-1 font-mono text-xs">
          {timeline.map((event) => (
            <div
              key={event.id}
              className="flex items-center justify-between p-2 rounded-lg bg-slate-950/70 border border-slate-800/80 hover:border-slate-700 transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <span className="text-slate-400 font-semibold text-[11px]">{event.time}</span>
                <span className={`px-2 py-0.5 rounded text-[11px] font-bold border ${getTimelineBadge(event.verdict)}`}>
                  {event.verdict}
                </span>
              </div>
              <span className="text-[11px] text-slate-400 truncate max-w-[130px]" title={event.detail}>
                {event.detail}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* CONVERSATION INTELLIGENCE (WHISPER ASR) */}
      <div className="rounded-xl bg-slate-900/60 border border-slate-800 p-4">
        <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-purple-400" />
            <span className="text-xs font-mono font-bold tracking-wider uppercase text-slate-200">
              Conversation Intelligence
            </span>
          </div>
          <span className="text-[10px] font-mono text-purple-400 uppercase font-semibold">
            WHISPER ASR
          </span>
        </div>

        {conversation ? (
          <div className="font-mono text-xs space-y-2 mt-2">
            <div className="flex justify-between items-center bg-purple-950/30 px-2.5 py-1.5 rounded border border-purple-800/40">
              <span className="text-slate-400">INTENT:</span>
              <span className="text-purple-300 font-bold">{conversation.intent}</span>
            </div>
            <div className="flex justify-between items-center bg-purple-950/20 px-2.5 py-1.5 rounded">
              <span className="text-slate-400">RISK SIGNAL:</span>
              <span className="text-rose-400 font-bold">{conversation.risk_signal.toFixed(2)}</span>
            </div>
            <div className="p-2 rounded bg-slate-950/60 border border-slate-800 text-[11px] text-slate-300 italic">
              "{conversation.evidence}"
            </div>
          </div>
        ) : (
          <div className="text-xs font-mono text-slate-500 italic py-2 text-center">
            No conversational risk intent flagged
          </div>
        )}
      </div>

      {/* ACTIVE CHALLENGE BANNER (DEMO KILLER FEATURE) */}
      {activeChallenge && (
        <div className="rounded-xl bg-purple-950/40 border border-purple-500/40 p-3.5 animate-pulse font-mono text-xs">
          <div className="flex items-center justify-between mb-1.5">
            <span className="font-bold text-purple-300 uppercase tracking-wider flex items-center gap-1.5">
              <AlertCircle className="w-3.5 h-3.5" /> ACTIVE CHALLENGE
            </span>
            <span className="text-[10px] text-purple-400">EXP: {activeChallenge.expires_in_sec}s</span>
          </div>
          <p className="text-white font-bold text-sm bg-purple-900/40 p-2 rounded border border-purple-700/50 text-center">
            "{activeChallenge.prompt}"
          </p>
        </div>
      )}

    </aside>
  );
};
