import React, { useState } from 'react';
import { ShieldCheck, Lock, EyeOff, CheckCircle2, X } from 'lucide-react';

interface ConsentModalProps {
  isOpen: boolean;
  onConsent: () => void;
  onCancel: () => void;
}

export const ConsentModal: React.FC<ConsentModalProps> = ({ isOpen, onConsent, onCancel }) => {
  const [agreed, setAgreed] = useState(false);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-cyan-500/50 rounded-xl max-w-xl w-full p-6 shadow-[0_0_40px_rgba(6,182,212,0.25)] text-slate-200 flex flex-col gap-5">
        
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-cyan-950/80 border border-cyan-500/40 text-cyan-400">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-base font-bold tracking-wider text-cyan-300 uppercase">
                Biometric Privacy & Consent Disclosure
              </h3>
              <p className="text-xs text-slate-400">GDPR Art. 9 & Illinois BIPA Compliance Mandate</p>
            </div>
          </div>
          <button
            onClick={onCancel}
            className="text-slate-500 hover:text-slate-300 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Core Principles */}
        <div className="flex flex-col gap-3 text-xs leading-relaxed text-slate-300">
          <div className="flex items-start gap-2.5 p-3 rounded-lg bg-slate-950/60 border border-slate-800">
            <EyeOff className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-cyan-300">Zero Raw Audio Retention:</span> Raw microphone speech is processed in volatile memory only and is <strong>never stored on disk</strong>, recorded, sold, or shared with third parties.
            </div>
          </div>

          <div className="flex items-start gap-2.5 p-3 rounded-lg bg-slate-950/60 border border-slate-800">
            <Lock className="w-4 h-4 text-purple-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-purple-300">Volatile Memory Scrubbing:</span> Audio buffers are immediately overwritten with zeros (<code className="text-cyan-300">secure_zero_memory</code>) within milliseconds after computing mathematical verification scores.
            </div>
          </div>

          <div className="flex items-start gap-2.5 p-3 rounded-lg bg-slate-950/60 border border-slate-800">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-emerald-300">AES-256-GCM Encryption:</span> Speaker voice embeddings are protected with authenticated encryption at rest and in transit.
            </div>
          </div>
        </div>

        {/* Explicit Opt-in Checkbox */}
        <label className="flex items-center gap-3 p-3 rounded-lg bg-cyan-950/30 border border-cyan-500/30 cursor-pointer hover:bg-cyan-950/50 transition-all">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="w-4 h-4 rounded border-cyan-500 text-cyan-500 focus:ring-cyan-400 focus:ring-offset-slate-900 cursor-pointer"
          />
          <span className="text-xs text-cyan-200 font-medium select-none">
            I explicitly consent to real-time acoustic analysis of my microphone stream for deepfake and voice security screening.
          </span>
        </label>

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold tracking-wider transition-colors cursor-pointer"
          >
            CANCEL
          </button>
          <button
            disabled={!agreed}
            onClick={onConsent}
            className={`px-5 py-2 rounded-lg text-xs font-bold tracking-wider transition-all flex items-center gap-2 cursor-pointer ${
              agreed
                ? 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 shadow-[0_0_15px_rgba(6,182,212,0.4)]'
                : 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
            <span>[I CONSENT & START MONITORING]</span>
          </button>
        </div>
      </div>
    </div>
  );
};
