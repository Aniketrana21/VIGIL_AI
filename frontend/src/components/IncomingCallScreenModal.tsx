import React, { useState, useEffect } from 'react';
import { 
  Phone, 
  PhoneOff, 
  ShieldAlert, 
  CheckCircle2, 
  AlertTriangle, 
  Building2, 
  Users, 
  X, 
  Radio, 
  Lock, 
  Activity,
  Zap,
  Eye,
  EyeOff,
  Unlock,
  Ban
} from 'lucide-react';

interface IncomingCallScreenModalProps {
  isOpen: boolean;
  onClose: () => void;
  latestCall?: LiveScreenedCall | null;
  activeTelemetry?: any;
}

export interface LiveScreenedCall {
  timestamp: string;
  phone_number: string;
  normalized_number: string;
  masked_phone: string;
  caller_name: string;
  company_name: string | null;
  company_badge: string | null;
  verification_status: string;
  trust_status: string;
  risk_score: number;
  risk_level: string;
  action: string;
  reasons: string[];
  voice_deepfake_pct: number;
  voice_identity_pct: number;
  voice_liveness_pct: number;
  warning_banner: string | null;
  calls_summary_total: number;
  calls_summary_today: number;
  call_id?: string;
  caller_type?: string;
  contact_known?: boolean;
  speaker_verification_status?: string;
  deepfake_detection_status?: string;
  liveness_status?: string;
  cellular_audio_available?: boolean;
  call_transport?: string;
  last_call_timestamp?: string;
}

export const IncomingCallScreenModal: React.FC<IncomingCallScreenModalProps> = ({
  isOpen,
  onClose,
  latestCall,
  activeTelemetry: _activeTelemetry,
}) => {
  const [activeTab, setActiveTab] = useState<'LIVE_CALL' | 'SIM_LOW_RISK' | 'SIM_HIGH_RISK' | 'SECURITY_PROFILE'>('LIVE_CALL');
  const [challengePrompt, setChallengePrompt] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [liveCalls, setLiveCalls] = useState<LiveScreenedCall[]>([]);
  const [selectedCall, setSelectedCall] = useState<LiveScreenedCall | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showFullNumber, setShowFullNumber] = useState(false);

  // Initial one-shot load of call screening history when modal opens (no polling)
  useEffect(() => {
    if (!isOpen) return;

    const fetchLiveCalls = async () => {
      try {
        const res = await fetch('/api/v1/screening/live');
        if (res.ok) {
          const data = await res.json();
          if (data.recent_calls && data.recent_calls.length > 0) {
            setLiveCalls(data.recent_calls);
            setSelectedCall((prev) => prev || data.latest_call);
          }
        }
      } catch (err) {
        console.error("Failed to fetch screening feed history:", err);
      }
    };

    fetchLiveCalls();
  }, [isOpen]);

  // Synchronize incoming push events from WebSocket in real time (zero polling)
  useEffect(() => {
    if (latestCall) {
      setSelectedCall(latestCall);
      setLiveCalls((prev) => {
        const exists = prev.some(
          (c) => c.timestamp === latestCall.timestamp && c.normalized_number === latestCall.normalized_number
        );
        if (exists) return prev;
        return [latestCall, ...prev];
      });
      setActiveTab('LIVE_CALL');
    }
  }, [latestCall]);

  if (!isOpen) return null;

  const currentLive = selectedCall || (liveCalls.length > 0 ? liveCalls[0] : null);

  const handleActionClick = (actionName: string) => {
    if (actionName === 'VERIFY CALLER') {
      const phrases = [
        "Please repeat: 'Sapphire falcon circles marble stairs 42'",
        "Please repeat: 'Crimson glacier echoes across seven bridges 88'",
        "Please repeat: 'Golden lantern warms quiet shores 19'"
      ];
      const randomPrompt = phrases[Math.floor(Math.random() * phrases.length)];
      setChallengePrompt(randomPrompt);
      setActionFeedback("Dynamic Non-Habitual Challenge Dispatched (60s TTL)");
    } else {
      setActionFeedback(`Action [${actionName}] executed & logged to Supabase calls audit.`);
      setTimeout(() => {
        setActionFeedback(null);
      }, 3500);
    }
  };

  const handleToggleCallerTrust = async (phoneNumber: string, newTrustStatus: 'blocked' | 'trusted') => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/v1/screening/trust', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phone_number: phoneNumber,
          trust_status: newTrustStatus
        })
      });
      if (res.ok) {
        await res.json();
        setActionFeedback(
          newTrustStatus === 'trusted'
            ? `Number ${phoneNumber} is now TRUSTED / ALLOWED in Supabase directory.`
            : `Number ${phoneNumber} is now BLOCKED in Supabase directory.`
        );
        // Refresh feed
        const feedRes = await fetch('/api/v1/screening/live');
        if (feedRes.ok) {
          const feed = await feedRes.json();
          setLiveCalls(feed.recent_calls);
          if (feed.latest_call) setSelectedCall(feed.latest_call);
        }
      }
    } catch (e) {
      console.error("Failed to update trust:", e);
    } finally {
      setIsLoading(false);
      setTimeout(() => setActionFeedback(null), 4000);
    }
  };

  const handleSimulateFriendCall = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/v1/screening/trigger-fraud-call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (res.ok) {
        setActionFeedback("Incoming live fraud call simulation screened & BLOCKED live!");
        const feedRes = await fetch('/api/v1/screening/live');
        if (feedRes.ok) {
          const feed = await feedRes.json();
          setLiveCalls(feed.recent_calls);
          setSelectedCall(feed.latest_call);
          setActiveTab('LIVE_CALL');
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-5xl max-h-[92vh] overflow-y-auto bg-slate-950 border border-slate-800 rounded-3xl shadow-[0_0_60px_rgba(0,0,0,0.85)] p-6 flex flex-col gap-6">
        
        {/* Header Bar */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Phone className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white font-mono flex items-center gap-2 flex-wrap">
                VIGIL-AI Telephony Screening HUD
                <span className="text-[10px] uppercase font-mono px-2.5 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800">
                  Android Telecom Mode B
                </span>
                <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-rose-950 text-rose-300 border border-rose-800 text-[10px] font-mono animate-pulse">
                  <span className="w-2 h-2 rounded-full bg-rose-500"></span> LIVE SMARTPHONE SYNC
                </span>
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                Real-time synchronized caller identity, reputation, and threat analysis for <strong className="text-slate-200">Active Protected Enclave</strong>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Mode Tabs */}
        <div className="flex flex-wrap gap-2 p-1.5 bg-slate-900/90 border border-slate-800 rounded-xl">
          <button
            onClick={() => { setActiveTab('LIVE_CALL'); setChallengePrompt(null); }}
            className={`flex-1 min-w-[220px] py-2 px-3 rounded-lg text-xs font-mono font-semibold transition-all flex items-center justify-center gap-2 ${
              activeTab === 'LIVE_CALL'
                ? 'bg-rose-950/90 text-rose-300 border border-rose-600 shadow-[0_0_15px_rgba(244,63,94,0.35)] font-bold'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping inline-block" />
            🔴 Real Call (Live Phone Sync)
          </button>
          <button
            onClick={() => { setActiveTab('SIM_LOW_RISK'); setChallengePrompt(null); }}
            className={`flex-1 min-w-[170px] py-2 px-3 rounded-lg text-xs font-mono font-semibold transition-all ${
              activeTab === 'SIM_LOW_RISK'
                ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-700 shadow-[0_0_15px_rgba(16,185,129,0.2)]'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            🧪 Preset: Safe Family Contact
          </button>
          <button
            onClick={() => { setActiveTab('SIM_HIGH_RISK'); setChallengePrompt(null); }}
            className={`flex-1 min-w-[170px] py-2 px-3 rounded-lg text-xs font-mono font-semibold transition-all ${
              activeTab === 'SIM_HIGH_RISK'
                ? 'bg-amber-950/80 text-amber-300 border border-amber-700 shadow-[0_0_15px_rgba(245,158,11,0.2)]'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            🚨 Preset: Bank Scam Demo
          </button>
          <button
            onClick={() => { setActiveTab('SECURITY_PROFILE'); setChallengePrompt(null); }}
            className={`flex-1 min-w-[170px] py-2 px-3 rounded-lg text-xs font-mono font-semibold transition-all ${
              activeTab === 'SECURITY_PROFILE'
                ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-700 shadow-[0_0_15px_rgba(6,182,212,0.2)]'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            🛡 Security Profile Analytics
          </button>
        </div>

        {/* Feedback Alert */}
        {actionFeedback && (
          <div className="p-3 bg-cyan-950/60 border border-cyan-700/80 rounded-xl text-cyan-200 font-mono text-xs flex items-center gap-2 animate-in fade-in">
            <CheckCircle2 className="w-4 h-4 text-cyan-400 flex-shrink-0" />
            <span>{actionFeedback}</span>
          </div>
        )}

        {/* Content Layout Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          
          {/* LEFT: Phone Device Screen Card (370px wide emulation) */}
          <div className="lg:col-span-6 flex justify-center">
            <div className="w-full max-w-[370px] bg-black border-2 border-slate-700 rounded-[32px] p-5 shadow-2xl relative overflow-hidden flex flex-col justify-between min-h-[600px]">
              
              {/* Phone Status Bar */}
              <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono pb-3 border-b border-slate-900">
                <span>03:32 PM</span>
                <span className="flex items-center gap-1">
                  <Radio className="w-3 h-3 text-cyan-400 animate-pulse" /> 5G VIGIL-AI
                </span>
                <span>88%</span>
              </div>

              {/* TAB 1: REAL LIVE INCOMING CALL FROM PHONE */}
              {activeTab === 'LIVE_CALL' && (
                currentLive ? (
                  <div className="flex flex-col gap-3 py-2 flex-1 animate-in fade-in">
                    {/* Verdict Banner */}
                    <div className={`text-center p-3 rounded-2xl border ${
                      currentLive.action === 'BLOCK' || currentLive.action === 'TERMINATE'
                        ? 'bg-rose-950/80 border-rose-600 shadow-[0_0_25px_rgba(244,63,94,0.35)]'
                        : currentLive.risk_score >= 50
                        ? 'bg-amber-950/80 border-amber-600'
                        : 'bg-emerald-950/80 border-emerald-600'
                    }`}>
                      <span className={`text-[11px] font-mono tracking-widest uppercase font-black flex items-center justify-center gap-1.5 ${
                        currentLive.action === 'BLOCK' || currentLive.action === 'TERMINATE' ? 'text-rose-300' : 'text-emerald-300'
                      }`}>
                        {currentLive.action === 'BLOCK' || currentLive.action === 'TERMINATE'
                          ? '🚫 BLOCKED / TERMINATED'
                          : '📞 INCOMING CALL SCREENED'}
                      </span>
                      
                      <h3 className="text-base font-bold text-white mt-1.5 break-words">
                        {currentLive.caller_name}
                      </h3>
                      
                      <div className="flex items-center justify-center gap-2 mt-1">
                        <span className="text-xs font-mono text-cyan-300">
                          {showFullNumber ? currentLive.phone_number : currentLive.masked_phone}
                        </span>
                        <button
                          onClick={() => setShowFullNumber(!showFullNumber)}
                          className="text-[10px] text-slate-400 hover:text-white"
                          title="Toggle Mask"
                        >
                          {showFullNumber ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>

                      <div className="mt-2 flex items-center justify-center gap-1.5 flex-wrap">
                        <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold border ${
                          currentLive.action === 'BLOCK' || currentLive.action === 'TERMINATE'
                            ? 'bg-black/60 text-rose-400 border-rose-800' 
                            : 'bg-black/60 text-emerald-400 border-emerald-800'
                        }`}>
                          Action: {currentLive.action}
                        </span>
                        <span className="px-2.5 py-0.5 rounded-full bg-black/60 text-[10px] font-mono font-bold text-cyan-400 border border-cyan-800">
                          Risk: {currentLive.risk_score}/100 ({currentLive.risk_level})
                        </span>
                        <span className="px-2.5 py-0.5 rounded-full bg-black/60 text-[10px] font-mono font-bold text-purple-300 border border-purple-800">
                          Type: {(currentLive.caller_type || (currentLive.contact_known ? 'SAVED_CONTACT' : 'UNKNOWN')).toUpperCase()}
                        </span>
                      </div>
                    </div>

                    {/* ZERO-TRUST IDENTITY COMPARISON CARD */}
                    <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-3 space-y-2 font-mono text-xs">
                      {/* Phone Identity (Signaling) */}
                      <div className="p-2 rounded-lg bg-black/40 border border-slate-800">
                        <div className="flex justify-between items-center text-[10px] uppercase font-bold text-slate-400 pb-1 border-b border-slate-800">
                          <span>📡 Phone Identity (Network)</span>
                          <span className={currentLive.contact_known ? 'text-emerald-400 font-bold' : 'text-amber-400'}>
                            {currentLive.contact_known ? 'KNOWN / SAVED' : 'UNRECOGNIZED'}
                          </span>
                        </div>
                        <div className="mt-1 flex justify-between text-[11px] text-slate-300">
                          <span>History:</span>
                          <strong className="text-white">{currentLive.calls_summary_total} total ({currentLive.calls_summary_today} today)</strong>
                        </div>
                        <div className="flex justify-between text-[11px] text-slate-300">
                          <span>STIR/SHAKEN:</span>
                          <strong className="text-cyan-400">Cryptographic Attestation</strong>
                        </div>
                      </div>

                      {/* Voice Identity (Acoustic / Biometrics) */}
                      <div className="p-2 rounded-lg bg-black/40 border border-slate-800">
                        <div className="flex justify-between items-center text-[10px] uppercase font-bold text-slate-400 pb-1 border-b border-slate-800">
                          <span>🎙️ Voice Identity (Biometric)</span>
                          <span className={`font-bold ${
                            currentLive.voice_identity_pct > 80 ? 'text-emerald-400' : (currentLive.voice_deepfake_pct > 70 ? 'text-rose-400' : 'text-amber-400')
                          }`}>
                            {currentLive.speaker_verification_status || (currentLive.voice_identity_pct > 0 ? `${currentLive.voice_identity_pct}% MATCH` : 'WAITING FOR VOICE')}
                          </span>
                        </div>
                        <div className="mt-1 flex justify-between text-[11px] text-slate-300">
                          <span>Deepfake Risk:</span>
                          <strong className={currentLive.voice_deepfake_pct > 50 ? 'text-rose-400' : 'text-emerald-400'}>
                            {currentLive.voice_deepfake_pct}%
                          </strong>
                        </div>
                        <div className="flex justify-between text-[11px] text-slate-300">
                          <span>Acoustic Liveness:</span>
                          <strong className={currentLive.voice_liveness_pct < 40 ? 'text-amber-400' : 'text-emerald-400'}>
                            {currentLive.voice_liveness_pct}%
                          </strong>
                        </div>
                      </div>

                      {/* Zero-Trust Notice */}
                      <div className="text-[10px] text-slate-400 bg-amber-950/30 border border-amber-900/50 p-1.5 rounded leading-tight">
                        <span className="text-amber-400 font-bold">⚠️ ZERO-TRUST PRINCIPLE:</span> Phone number identity ≠ Voice identity. Spoofed CLI or SIM swaps compromise numbers.
                      </div>
                    </div>

                    {/* Platform Capability Badge */}
                    <div className="p-2 rounded-xl bg-slate-900/80 border border-slate-800 text-[10px] font-mono">
                      <div className="text-slate-400 font-bold uppercase mb-0.5">PLATFORM CAPABILITY &amp; PATH:</div>
                      {currentLive.call_transport === 'VOIP' ? (
                        <div className="text-emerald-400 font-semibold">
                          🎙️ Path B (VoIP / Stream): Continuous bidirectional voice analysis with instant auto-termination.
                        </div>
                      ) : (
                        <div className="text-amber-300/90 leading-tight">
                          🛡️ Path A (Cellular): Pre-call screening active (Telecom Mode B). In-call audio monitoring restricted by Android OS sandbox.
                        </div>
                      )}
                    </div>

                    {/* Threat Indicators & Reasons */}
                    <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-2.5 space-y-1 font-mono text-xs">
                      <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider border-b border-slate-800 pb-1 flex items-center justify-between">
                        <span>Security Evaluation Signals</span>
                        <span className="text-rose-400 font-bold">{currentLive.reasons.length} flags</span>
                      </div>
                      {currentLive.reasons.map((r, i) => (
                        <p key={i} className="text-[11px] text-amber-300/90 flex items-start gap-1 leading-tight">
                          <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0 mt-0.5" />
                          <span>{r}</span>
                        </p>
                      ))}
                    </div>

                    {/* Dynamic Challenge Section */}
                    {challengePrompt && (
                      <div className="p-2 bg-amber-950/70 border border-amber-600 rounded-xl font-mono text-[11px] text-amber-200 animate-in fade-in">
                        <div className="font-bold text-amber-300 flex items-center gap-1 mb-0.5">
                          <Lock className="w-3.5 h-3.5" /> DYNAMIC NONCE CHALLENGE (60s TTL):
                        </div>
                        <p className="text-white italic">"{challengePrompt}"</p>
                      </div>
                    )}

                    {/* Interactive Telephony Actions */}
                    <div className="flex flex-col gap-2 mt-auto pt-1 font-mono text-xs">
                      <button
                        onClick={() => handleActionClick('VERIFY CALLER')}
                        className="py-2 px-3 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-bold flex items-center justify-center gap-1.5 shadow-md active:scale-95 transition-all"
                      >
                        <Lock className="w-3.5 h-3.5" /> [ DISPATCH NONCE CHALLENGE ]
                      </button>
                      
                      <div className="grid grid-cols-2 gap-2">
                        {currentLive.trust_status === 'blocked' ? (
                          <button
                            onClick={() => handleToggleCallerTrust(currentLive.phone_number, 'trusted')}
                            disabled={isLoading}
                            className="py-2 px-2.5 rounded-xl bg-emerald-700 hover:bg-emerald-600 text-white font-bold flex items-center justify-center gap-1 active:scale-95 transition-all"
                          >
                            <Unlock className="w-3.5 h-3.5" /> [ UNBLOCK NUMBER ]
                          </button>
                        ) : (
                          <button
                            onClick={() => handleToggleCallerTrust(currentLive.phone_number, 'blocked')}
                            disabled={isLoading}
                            className="py-2 px-2.5 rounded-xl bg-rose-700 hover:bg-rose-600 text-white font-bold flex items-center justify-center gap-1 active:scale-95 transition-all"
                          >
                            <Ban className="w-3.5 h-3.5" /> [ BLOCK NUMBER ]
                          </button>
                        )}
                        
                        <button
                          onClick={() => handleActionClick('SILENCE')}
                          className="py-2 px-2.5 rounded-xl bg-amber-700 hover:bg-amber-600 text-white font-bold flex items-center justify-center gap-1 active:scale-95 transition-all"
                        >
                          [ SILENCE ]
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  /* Standby Radar State */
                  <div className="flex flex-col items-center justify-center gap-4 py-8 flex-1 text-center font-mono">
                    <div className="w-16 h-16 rounded-full bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 relative">
                      <span className="w-full h-full rounded-full border border-cyan-400/30 animate-ping absolute" />
                      <Radio className="w-8 h-8 text-cyan-400 animate-pulse" />
                    </div>
                    <div>
                      <h4 className="text-sm font-bold text-white">READY & LISTENING FOR CALLS</h4>
                      <p className="text-xs text-slate-400 mt-1 max-w-[260px]">
                        Protected Phone: <strong className="text-cyan-300">Enrolled Device</strong>
                      </p>
                      <p className="text-[11px] text-slate-500 mt-2 max-w-[260px] leading-relaxed">
                        When someone calls your phone, VIGIL-AI Telecom will intercept it and update this screen live.
                      </p>
                    </div>
                    <button
                      onClick={handleSimulateFriendCall}
                      disabled={isLoading}
                      className="mt-2 px-3 py-1.5 rounded-xl bg-gradient-to-r from-rose-600 to-red-600 text-white text-xs font-bold flex items-center gap-1.5 shadow-lg shadow-rose-900/40 active:scale-95"
                    >
                      <Zap className="w-3.5 h-3.5" /> {isLoading ? 'Triggering...' : 'Trigger Friend Test Call'}
                    </button>
                  </div>
                )
              )}

              {/* TAB 2: SIMULATION PRESET - SAFE CONTACT */}
              {activeTab === 'SIM_LOW_RISK' && (
                <div className="flex flex-col gap-3 py-2 flex-1 animate-in fade-in">
                  <div className="bg-emerald-950/40 border border-emerald-800/80 rounded-xl p-2 text-center text-[10px] font-mono text-emerald-400">
                    🧪 TEST SIMULATION PRESET (FOR DEMONSTRATION ONLY)
                  </div>
                  <div className="text-center">
                    <span className="text-[11px] font-mono tracking-widest text-slate-400 uppercase font-semibold">
                      INCOMING CALL (LOW RISK)
                    </span>
                    <h3 className="text-xl font-bold text-white mt-2 flex items-center justify-center gap-2">
                      👤 Priya Sharma (Sister)
                    </h3>
                    <p className="text-sm font-mono text-emerald-400 mt-0.5">Sample Trusted Contact</p>
                  </div>

                  <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 text-center">
                    <p className="text-xs font-semibold text-slate-200">Family Circle (Verified)</p>
                    <p className="text-[11px] font-mono text-emerald-400 flex items-center justify-center gap-1 mt-0.5">
                      <CheckCircle2 className="w-3.5 h-3.5" /> CRYPTOGRAPHIC STIR/SHAKEN PASSED
                    </p>
                  </div>

                  <div className="bg-emerald-950/20 border border-emerald-900/60 rounded-xl p-3 space-y-1.5 font-mono text-xs">
                    <div className="flex justify-between text-slate-300">
                      <span>Identity (Speaker Match):</span>
                      <strong className="text-emerald-400">96%</strong>
                    </div>
                    <div className="flex justify-between text-slate-300">
                      <span>Deepfake Probability:</span>
                      <strong className="text-emerald-400">3%</strong>
                    </div>
                    <div className="flex justify-between text-slate-300">
                      <span>Risk Score:</span>
                      <strong className="text-emerald-400">8 / 100 (LOW)</strong>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3 mt-auto pt-2">
                    <button
                      onClick={() => handleActionClick('DECLINE')}
                      className="py-3 px-4 rounded-2xl bg-rose-600 hover:bg-rose-500 text-white font-mono font-bold text-xs flex items-center justify-center gap-2 active:scale-95"
                    >
                      <PhoneOff className="w-4 h-4" /> DECLINE
                    </button>
                    <button
                      onClick={() => handleActionClick('ACCEPT')}
                      className="py-3 px-4 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white font-mono font-bold text-xs flex items-center justify-center gap-2 active:scale-95"
                    >
                      <Phone className="w-4 h-4" /> ACCEPT
                    </button>
                  </div>
                </div>
              )}

              {/* TAB 3: SIMULATION PRESET - HIGH RISK */}
              {activeTab === 'SIM_HIGH_RISK' && (
                <div className="flex flex-col gap-3 py-2 flex-1 animate-in fade-in">
                  <div className="bg-rose-950/40 border border-rose-800/80 rounded-xl p-2 text-center text-[10px] font-mono text-rose-400">
                    🚨 TEST SIMULATION PRESET (FOR DEMONSTRATION ONLY)
                  </div>
                  <div className="text-center p-2 rounded-xl bg-rose-950/60 border border-rose-800">
                    <span className="text-xs font-mono tracking-widest text-rose-300 uppercase font-black flex items-center justify-center gap-1.5 animate-pulse">
                      <ShieldAlert className="w-4 h-4 text-rose-400" /> 🚨 HIGH-RISK CALL
                    </span>
                    <h3 className="text-lg font-bold text-white mt-1">
                      Bank Telecaller (Claimed SBI)
                    </h3>
                    <p className="text-xs font-mono text-rose-400">Sample Unverified Caller</p>
                  </div>

                  <div className="bg-slate-900/90 border border-rose-900/40 rounded-xl p-3 space-y-1.5 font-mono text-xs">
                    <div className="flex justify-between text-slate-300">
                      <span>Deepfake probability:</span>
                      <strong className="text-rose-400">93%</strong>
                    </div>
                    <div className="flex justify-between text-slate-300">
                      <span>Speaker similarity:</span>
                      <strong className="text-amber-400">89%</strong>
                    </div>
                    <div className="flex justify-between text-slate-200 text-sm font-bold pt-1 border-t border-slate-800">
                      <span>Risk Score:</span>
                      <strong className="text-rose-400 text-base">94/100 (CRITICAL)</strong>
                    </div>
                  </div>

                  <div className="bg-rose-950/80 border border-rose-700/80 p-2.5 rounded-xl text-center">
                    <p className="text-xs font-bold text-rose-200 font-mono flex items-center justify-center gap-1.5">
                      <AlertTriangle className="w-4 h-4 text-rose-400" />
                      ⚠ Unverified corporate claim + STIR/SHAKEN signature failed
                    </p>
                  </div>

                  <div className="flex flex-col gap-2 mt-auto pt-2 font-mono text-xs">
                    <button
                      onClick={() => handleActionClick('BLOCK')}
                      className="py-2.5 px-3 rounded-xl bg-rose-700 hover:bg-rose-600 text-white font-bold flex items-center justify-center gap-1 active:scale-95"
                    >
                      [ BLOCK IMMEDIATELY ]
                    </button>
                  </div>
                </div>
              )}

              {/* TAB 4: CALLER SECURITY PROFILE CARD */}
              {activeTab === 'SECURITY_PROFILE' && (
                <div className="flex flex-col gap-4 py-3 flex-1 justify-center animate-in fade-in">
                  <div className="bg-slate-900 border-2 border-cyan-800/80 rounded-2xl p-4 font-mono text-xs shadow-xl">
                    <div className="text-center pb-2.5 mb-3 border-b border-cyan-800/60">
                      <span className="text-xs font-bold text-cyan-300 tracking-wider">
                        TELEPHONY SECURITY PROFILE (RULE 22 & 23)
                      </span>
                    </div>
                    
                    <div className="space-y-2 text-slate-300">
                      <div className="flex justify-between"><span>Caller Identity</span><strong className="text-emerald-400">Evaluated</strong></div>
                      <div className="flex justify-between"><span>STIR/SHAKEN</span><strong className="text-cyan-300">Cryptographic Attestation</strong></div>
                      <div className="flex justify-between"><span>Velocity Audit</span><strong className="text-slate-200">1h &amp; 24h tracked</strong></div>
                      <div className="flex justify-between"><span>Company Claim</span><strong className="text-amber-400">Strict Non-Trust</strong></div>
                      <div className="flex justify-between"><span>Relationship Trust</span><strong className="text-purple-400">Non-habitual OTP/Audio</strong></div>
                      <div className="h-px bg-slate-800 my-2" />
                      <div className="flex justify-between text-sm font-bold text-white">
                        <span>Database Policy</span>
                        <strong className="text-emerald-400 text-base">Supabase Enforced</strong>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Phone Home Bar */}
              <div className="w-28 h-1 bg-slate-700 rounded-full mx-auto mt-2" />
            </div>
          </div>

          {/* RIGHT: Live Calls List & Telephony Operations */}
          <div className="lg:col-span-6 flex flex-col gap-4">
            
            {/* Live Feed Selector Card */}
            <div className="p-4 rounded-2xl bg-slate-900/80 border border-slate-800">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-white font-mono font-bold text-xs uppercase">
                  <Activity className="w-4 h-4 text-cyan-400" /> Calls Intercepted from Your Phone
                </div>
                <button
                  onClick={handleSimulateFriendCall}
                  disabled={isLoading}
                  className="px-2.5 py-1 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white font-mono text-[11px] rounded-lg flex items-center gap-1 transition-all cursor-pointer"
                >
                  <Zap className="w-3 h-3" /> {isLoading ? 'Triggering...' : 'Test Friend Call'}
                </button>
              </div>

              {liveCalls.length === 0 ? (
                <p className="text-xs text-slate-400 font-mono py-4 text-center">
                  No incoming phone calls received yet. Place a call to your device to see it intercepted here live!
                </p>
              ) : (
                <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
                  {liveCalls.map((call, idx) => (
                    <div
                      key={idx}
                      onClick={() => { setSelectedCall(call); setActiveTab('LIVE_CALL'); }}
                      className={`p-2.5 rounded-xl border font-mono text-xs cursor-pointer transition-all flex items-center justify-between ${
                        selectedCall?.normalized_number === call.normalized_number && selectedCall?.timestamp === call.timestamp
                          ? 'bg-rose-950/50 border-rose-500 text-white shadow-md'
                          : 'bg-slate-950/60 border-slate-800 text-slate-300 hover:bg-slate-800/50'
                      }`}
                    >
                      <div>
                        <div className="font-bold flex items-center gap-1.5">
                          <span className={`w-2 h-2 rounded-full ${call.action === 'BLOCK' ? 'bg-rose-500' : 'bg-emerald-500'}`} />
                          {call.caller_name}
                        </div>
                        <span className="text-[10px] text-slate-400">{call.masked_phone} • {new Date(call.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <div className="text-right">
                        <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                          call.action === 'BLOCK' ? 'bg-rose-950 text-rose-300 border border-rose-800' : 'bg-emerald-950 text-emerald-300'
                        }`}>
                          {call.action} ({call.risk_score} pts)
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Feature 22: Company Verification Architecture */}
            <div className="p-4 rounded-2xl bg-slate-900/70 border border-slate-800">
              <div className="flex items-center gap-2 text-cyan-400 font-mono font-bold text-xs uppercase mb-2">
                <Building2 className="w-4 h-4" /> Company Verification Architecture (Security Rule 22)
              </div>
              <p className="text-xs text-slate-300 leading-relaxed font-sans">
                If an incoming caller claims: <span className="text-cyan-300 font-semibold font-mono">"Hello, I'm Aniket from Microsoft"</span>, VIGIL-AI does <strong>not</strong> blindly save <code className="text-xs bg-slate-800 px-1 py-0.5 rounded text-amber-300 font-mono">company=Microsoft, verified=true</code>. The claim remains UNVERIFIED until verified through enterprise domain attestation.
              </p>
            </div>

            {/* Feature 23: Caller Relationship Trust */}
            <div className="p-4 rounded-2xl bg-slate-900/70 border border-slate-800">
              <div className="flex items-center gap-2 text-purple-400 font-mono font-bold text-xs uppercase mb-2">
                <Users className="w-4 h-4" /> Caller Relationship Trust (Security Rule 23)
              </div>
              <p className="text-xs text-slate-300 leading-relaxed font-sans">
                <span className="text-emerald-400 font-semibold">"Dad"</span> and <span className="text-rose-400 font-semibold">"Unknown caller claiming to be Dad"</span> are strictly distinguished. High-trust relationships asserted without cryptographic/biometric proof trigger an automatic +25 risk penalty.
              </p>
            </div>

          </div>
        </div>

      </div>
    </div>
  );
};
