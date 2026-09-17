import React from 'react';
import { UserCheck, HelpCircle, AlertOctagon, Ban, PlayCircle } from 'lucide-react';

interface BottomActionBarProps {
  onVerifyIdentity: () => void;
  onChallenge: () => void;
  onWarn: () => void;
  onBlock: () => void;
  onSimulateScenario: (scenario: 'GENUINE' | 'CLONED' | 'REPLAY' | 'SCAM') => void;
}

export const BottomActionBar: React.FC<BottomActionBarProps> = ({
  onVerifyIdentity,
  onChallenge,
  onWarn,
  onBlock,
  onSimulateScenario,
}) => {
  return (
    <footer className="w-full bg-slate-950/80 backdrop-blur border-t border-cyan-950/60 p-4 sticky bottom-0 z-50">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
        
        {/* MANDATORY BOTTOM ACTIONS: [VERIFY IDENTITY] [CHALLENGE] [WARN] [BLOCK] */}
        <div className="flex flex-wrap items-center gap-3 w-full md:w-auto font-mono text-xs">
          <span className="text-[11px] text-slate-400 font-semibold tracking-wider uppercase mr-1 hidden sm:inline">
            OPERATOR ACTIONS:
          </span>

          <button
            onClick={onVerifyIdentity}
            className="flex-1 sm:flex-none px-4 py-2.5 rounded-lg bg-cyan-950/40 hover:bg-cyan-900/60 border border-cyan-500/50 text-cyan-300 font-bold tracking-wider flex items-center justify-center gap-2 transition-all shadow-[0_0_10px_rgba(6,182,212,0.15)] cursor-pointer"
          >
            <UserCheck className="w-4 h-4" />
            <span>[VERIFY IDENTITY]</span>
          </button>

          <button
            onClick={onChallenge}
            className="flex-1 sm:flex-none px-4 py-2.5 rounded-lg bg-purple-950/40 hover:bg-purple-900/60 border border-purple-500/50 text-purple-300 font-bold tracking-wider flex items-center justify-center gap-2 transition-all shadow-[0_0_10px_rgba(168,85,247,0.15)] cursor-pointer"
          >
            <HelpCircle className="w-4 h-4" />
            <span>[CHALLENGE]</span>
          </button>

          <button
            onClick={onWarn}
            className="flex-1 sm:flex-none px-4 py-2.5 rounded-lg bg-amber-950/40 hover:bg-amber-900/60 border border-amber-500/50 text-amber-300 font-bold tracking-wider flex items-center justify-center gap-2 transition-all shadow-[0_0_10px_rgba(245,158,11,0.15)] cursor-pointer"
          >
            <AlertOctagon className="w-4 h-4" />
            <span>[WARN]</span>
          </button>

          <button
            onClick={onBlock}
            className="flex-1 sm:flex-none px-4 py-2.5 rounded-lg bg-rose-950/50 hover:bg-rose-900/70 border border-rose-500/60 text-rose-300 font-black tracking-wider flex items-center justify-center gap-2 transition-all shadow-[0_0_15px_rgba(244,63,94,0.25)] cursor-pointer"
          >
            <Ban className="w-4 h-4" />
            <span>[BLOCK]</span>
          </button>
        </div>

        {/* DEMO / JUDGES SIMULATOR TRIGGERS */}
        <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] w-full md:w-auto justify-end border-t md:border-t-0 pt-3 md:pt-0 border-slate-800">
          <span className="text-slate-400 font-semibold uppercase flex items-center gap-1">
            <PlayCircle className="w-3.5 h-3.5 text-cyan-400" />
            DEMO SIMULATOR:
          </span>

          <button
            onClick={() => onSimulateScenario('GENUINE')}
            className="px-2.5 py-1.5 rounded bg-slate-900 hover:bg-emerald-950/50 border border-slate-700 hover:border-emerald-500/50 text-slate-300 hover:text-emerald-300 transition-all cursor-pointer"
          >
            Genuine Call
          </button>

          <button
            onClick={() => onSimulateScenario('CLONED')}
            className="px-2.5 py-1.5 rounded bg-slate-900 hover:bg-rose-950/50 border border-slate-700 hover:border-rose-500/50 text-slate-300 hover:text-rose-300 transition-all cursor-pointer"
          >
            Voice Clone
          </button>

          <button
            onClick={() => onSimulateScenario('REPLAY')}
            className="px-2.5 py-1.5 rounded bg-slate-900 hover:bg-amber-950/50 border border-slate-700 hover:border-amber-500/50 text-slate-300 hover:text-amber-300 transition-all cursor-pointer"
          >
            Loudspeaker Replay
          </button>

          <button
            onClick={() => onSimulateScenario('SCAM')}
            className="px-2.5 py-1.5 rounded bg-slate-900 hover:bg-purple-950/50 border border-slate-700 hover:border-purple-500/50 text-slate-300 hover:text-purple-300 transition-all cursor-pointer font-bold"
          >
            OTP Scam
          </button>
        </div>

      </div>
    </footer>
  );
};
