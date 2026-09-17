import React, { useState, useEffect } from 'react';
import type { SecurityTelemetry, SIHScenarioMeta } from '../types';

interface SihDemoControllerProps {
  telemetry: SecurityTelemetry;
  onUpdateTelemetry: (newTelemetry: Partial<SecurityTelemetry>) => void;
}

const DEFENSE_STAGES = [
  { key: 'DETECT', label: '1. DETECT', desc: 'WavLM-AASIST Spectral Artifacts', icon: '🔍' },
  { key: 'VERIFY', label: '2. VERIFY', desc: 'ECAPA-TDNN Biometric Identity', icon: '👤' },
  { key: 'UNDERSTAND', label: '3. UNDERSTAND', desc: 'Whisper Contextual Intent (CI)', icon: '🧠' },
  { key: 'CHALLENGE', label: '4. CHALLENGE', desc: 'Phonetic Liveness Challenge', icon: '⚡' },
  { key: 'PREVENT', label: '5. PREVENT', desc: 'Telecom Reject & Carrier Attestation', icon: '🛡️' },
];

export const SihDemoController: React.FC<SihDemoControllerProps> = ({
  telemetry,
  onUpdateTelemetry,
}) => {
  const [scenarios, setScenarios] = useState<SIHScenarioMeta[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<number>(1);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [isStreamingWs, setIsStreamingWs] = useState<boolean>(false);
  const [wsProgress, setWsProgress] = useState<{ current: number; total: number } | null>(null);

  // Fetch all 5 scenarios on mount
  useEffect(() => {
    fetch('/api/v1/demo/scenarios')
      .then((res) => res.json())
      .then((data) => {
        if (data.scenarios) {
          setScenarios(data.scenarios);
        }
      })
      .catch((err) => console.error('Failed to load demo scenarios:', err));
  }, []);

  const activeScenario = scenarios.find((s) => s.id === selectedScenarioId) || scenarios[0];

  // Execute scenario via REST endpoint (deterministic batch run)
  const handleRunScenario = async (scenarioId: number) => {
    setIsRunning(true);
    try {
      const res = await fetch('/api/v1/demo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: scenarioId }),
      });
      const data = await res.json();
      if (data.status === 'SUCCESS') {
        onUpdateTelemetry({
          session_id: data.session_id,
          demo_mode: true,
          demo_scenario_id: scenarioId,
          defense_stage: data.scenario.defense_stage,
          voice_authenticity: data.metrics.voice_authenticity,
          speaker_match: data.metrics.speaker_match,
          liveness: data.metrics.liveness,
          deepfake_probability: data.metrics.deepfake_probability,
          risk_score: data.metrics.risk_score,
          risk_level: data.metrics.risk_level,
          action: data.metrics.action,
          confidence: data.metrics.confidence,
          latency_ms: data.metrics.latency_ms,
          threat_signals: data.signals || [],
          timeline: data.timeline || [],
          conversation: data.conversation || null,
          audio_chunks_processed: data.audio_chunks_processed,
          waveform_sample: data.waveform_sample,
          explanation: data.explanation,
        });
      }
    } catch (error) {
      console.error('Error running scenario:', error);
    } finally {
      setIsRunning(false);
    }
  };

  // Stream scenario live over WebSocket
  const handleStreamLive = (scenarioId: number) => {
    if (isStreamingWs) return;
    setIsStreamingWs(true);
    setWsProgress({ current: 0, total: 15 });

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host.includes(':5173') ? '127.0.0.1:8000' : window.location.host;
    const wsUrl = `${protocol}//${host}/api/v1/demo/stream/${scenarioId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === 'DEMO_CHUNK') {
          setWsProgress({ current: msg.chunk_index, total: msg.total_chunks });
          onUpdateTelemetry({
            session_id: msg.session_id,
            demo_mode: true,
            demo_scenario_id: scenarioId,
            defense_stage: msg.defense_stage,
            voice_authenticity: msg.metrics.voice_authenticity,
            speaker_match: msg.metrics.speaker_match,
            liveness: msg.metrics.liveness,
            deepfake_probability: msg.metrics.deepfake_probability,
            risk_score: msg.metrics.risk_score,
            risk_level: msg.metrics.risk_level,
            action: msg.metrics.action,
            confidence: msg.metrics.confidence,
            latency_ms: msg.metrics.latency_ms,
            threat_signals: msg.signals || [],
            conversation: msg.conversation || null,
            audio_chunks_processed: msg.chunk_index,
            waveform_sample: msg.waveform,
            explanation: msg.explanation,
          });
        } else if (msg.type === 'DEMO_COMPLETE') {
          setIsStreamingWs(false);
          ws.close();
        }
      } catch (e) {
        console.error('Error parsing demo stream chunk:', e);
      }
    };

    ws.onerror = () => setIsStreamingWs(false);
    ws.onclose = () => setIsStreamingWs(false);
  };

  return (
    <div className="bg-slate-900/95 border border-cyan-500/40 rounded-xl p-4 shadow-2xl backdrop-blur-md mb-6 relative overflow-hidden">
      {/* Background Accent Grid */}
      <div className="absolute -right-16 -top-16 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

      {/* Top Banner with DEMO MODE Indicator & Consent Disclosure */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-cyan-950/80 border border-cyan-400 px-3 py-1 rounded-full shadow-[0_0_15px_rgba(6,182,212,0.5)]">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
            <span className="text-xs font-mono font-bold tracking-widest text-cyan-200">
              SIH DEMO MODE ACTIVE
            </span>
          </div>
          <span className="text-xs text-slate-400 font-mono hidden sm:inline">
            Zero Faked Metrics • Real-Time Neural Pipeline
          </span>
        </div>

        {/* Consented Test Data Badge */}
        <div className="flex items-center gap-2 bg-slate-800/80 border border-slate-700 px-3 py-1 rounded text-xs text-slate-300 font-mono">
          <span className="text-emerald-400 font-bold">✓</span>
          <span>Consented Benchmark Data: ASVspoof 5 / IndicBench</span>
        </div>
      </div>

      {/* 5 Scenario Selector Tabs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-2 my-4">
        {scenarios.map((sc) => {
          const isSelected = selectedScenarioId === sc.id;
          const badgeColor =
            sc.expected_action === 'BLOCK'
              ? 'border-red-500/80 text-red-400 bg-red-950/40'
              : sc.expected_action === 'WARN'
              ? 'border-amber-500/80 text-amber-400 bg-amber-950/40'
              : sc.expected_action === 'CHALLENGE'
              ? 'border-yellow-500/80 text-yellow-300 bg-yellow-950/40'
              : 'border-emerald-500/80 text-emerald-400 bg-emerald-950/40';

          return (
            <button
              key={sc.id}
              onClick={() => setSelectedScenarioId(sc.id)}
              className={`p-2.5 rounded-lg border text-left transition-all duration-200 flex flex-col justify-between ${
                isSelected
                  ? 'bg-slate-800 border-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.3)] ring-1 ring-cyan-400'
                  : 'bg-slate-950/60 border-slate-800 hover:border-slate-700 hover:bg-slate-800/50'
              }`}
            >
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-mono font-bold text-slate-200">
                    SCENARIO {sc.id}
                  </span>
                  <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border ${badgeColor}`}>
                    {sc.expected_action}
                  </span>
                </div>
                <div className="text-xs font-medium text-slate-300 line-clamp-1">
                  {sc.title.split(': ')[1] || sc.title}
                </div>
              </div>
              <div className="text-[11px] text-slate-400 font-mono mt-1">
                {sc.expected_risk_level} RISK
              </div>
            </button>
          );
        })}
      </div>

      {/* SIH 5-Stage Defense Flow Tracker: DETECT -> VERIFY -> UNDERSTAND -> CHALLENGE -> PREVENT */}
      <div className="bg-slate-950/80 border border-slate-800/80 rounded-lg p-3 my-3">
        <div className="text-[11px] font-mono tracking-wider text-slate-400 uppercase mb-2 flex items-center justify-between">
          <span>VIGIL-AI 5-Stage Defensive Progression</span>
          <span className="text-cyan-400">
            Active: {telemetry.defense_stage || activeScenario?.defense_stage || 'DETECT'}
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {DEFENSE_STAGES.map((st) => {
            const isCurrent =
              (telemetry.defense_stage || activeScenario?.defense_stage) === st.key;
            return (
              <div
                key={st.key}
                className={`p-2 rounded border transition-all ${
                  isCurrent
                    ? 'bg-cyan-950/70 border-cyan-400 text-cyan-200 shadow-[0_0_10px_rgba(6,182,212,0.4)]'
                    : 'bg-slate-900/50 border-slate-800 text-slate-400'
                }`}
              >
                <div className="flex items-center gap-1.5 text-xs font-bold font-mono mb-0.5">
                  <span>{st.icon}</span>
                  <span>{st.label}</span>
                </div>
                <div className="text-[10px] text-slate-400 leading-tight">
                  {st.desc}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Active Scenario Details & Live Controls */}
      {activeScenario && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 pt-2">
          {/* Transcript & Description */}
          <div className="lg:col-span-2 bg-slate-950/60 border border-slate-800 rounded-lg p-3">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-1">
              <span className="font-bold text-cyan-400">{activeScenario.title}</span>
              <span>Outcome: {activeScenario.expected_outcome}</span>
            </div>
            <p className="text-xs text-slate-300 mb-2 leading-relaxed">
              {activeScenario.description}
            </p>
            <div className="bg-slate-900/90 border border-slate-800 rounded p-2 text-xs font-mono">
              <span className="text-slate-500">Audio Transcript: </span>
              <span className="text-emerald-300 italic">
                "{activeScenario.conversation_transcript}"
              </span>
            </div>
          </div>

          {/* Action Execution Buttons & Live Metrics */}
          <div className="flex flex-col justify-between gap-2 bg-slate-950/60 border border-slate-800 rounded-lg p-3">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400">
              <span>Streaming Pipeline:</span>
              <span className="text-cyan-400">16kHz PCM16</span>
            </div>

            {wsProgress && isStreamingWs && (
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden my-1">
                <div
                  className="bg-cyan-400 h-1.5 transition-all duration-100"
                  style={{ width: `${(wsProgress.current / wsProgress.total) * 100}%` }}
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => handleRunScenario(selectedScenarioId)}
                disabled={isRunning || isStreamingWs}
                className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white font-mono font-bold py-2 px-3 rounded text-xs transition shadow-lg shadow-cyan-600/30 flex items-center justify-center gap-1.5"
              >
                {isRunning ? (
                  <>
                    <span className="animate-spin">⚙</span> Evaluating...
                  </>
                ) : (
                  <>
                    <span>▶</span> RUN BATCH
                  </>
                )}
              </button>

              <button
                onClick={() => handleStreamLive(selectedScenarioId)}
                disabled={isRunning || isStreamingWs}
                className="w-full bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white font-mono font-bold py-2 px-3 rounded text-xs transition shadow-lg shadow-emerald-700/30 flex items-center justify-center gap-1.5"
              >
                {isStreamingWs ? (
                  <>
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" /> Streaming...
                  </>
                ) : (
                  <>
                    <span>⚡</span> LIVE STREAM
                  </>
                )}
              </button>
            </div>

            <div className="text-[10px] text-slate-400 font-mono text-center">
              Chunks: {telemetry.audio_chunks_processed || 0} • Latency: {telemetry.latency_ms}ms • Engine: WavLM-AASIST
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
