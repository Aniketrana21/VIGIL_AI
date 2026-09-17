/**
 * VIGIL-AI Phase 1: Real-Time Audio Ingestion Pipeline
 * WebSocket client, Web Audio API 16kHz microphone capture, and Live Telemetry Dashboard
 */

let ws = null;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let isRecording = false;
let clientSequenceCounter = 0;

// DOM Elements
const wsStatus = document.getElementById("ws-status");
const statusLabel = document.getElementById("status-label");
const globalLatency = document.getElementById("global-latency");
const btnToggleMic = document.getElementById("btn-toggle-mic");
const canvas = document.getElementById("canvas-visualizer");
const canvasCtx = canvas.getContext("2d");
const vadBadge = document.getElementById("vad-badge");
const vadText = document.getElementById("vad-text");
const audioStatePill = document.getElementById("audio-state-pill");

// Phase 2 VAD Elements
const dispVadPct = document.getElementById("disp-vad-pct");
const vadMeterFill = document.getElementById("vad-meter-fill");
const dispVadState = document.getElementById("disp-vad-state");
const dispVadTimestamps = document.getElementById("disp-vad-timestamps");
const dispVadLatency = document.getElementById("disp-vad-latency");

// Phase 3 Deepfake Elements
const dfVerdictBadge = document.getElementById("df-verdict-badge");
const dispDfSpoof = document.getElementById("disp-df-spoof");
const dispDfBonafide = document.getElementById("disp-df-bonafide");
const dispDfConfidence = document.getElementById("disp-df-confidence");
const dispDfLatency = document.getElementById("disp-df-latency");
const dfTimelineList = document.getElementById("df-timeline-list");

// Phase 5 Speaker Verification Elements
const spkMatchBadge = document.getElementById("spk-match-badge");
const dispSpkId = document.getElementById("disp-spk-id");
const dispSpkSimilarity = document.getElementById("disp-spk-similarity");
const dispSpkMatch = document.getElementById("disp-spk-match");
const dispSpkConfidence = document.getElementById("disp-spk-confidence");

// Phase 6 Multi-Signal Risk Engine Elements
const riskActionBadge = document.getElementById("risk-action-badge");
const dispRiskScore = document.getElementById("disp-risk-score");
const dispRiskLevel = document.getElementById("disp-risk-level");
const dispRiskAction = document.getElementById("disp-risk-action");
const riskMeterFill = document.getElementById("risk-meter-fill");
const dispRiskSignalsCount = document.getElementById("disp-risk-signals-count");
const riskContributingList = document.getElementById("risk-contributing-list");

// Phase 9 Liveness & Replay Elements
const livenessBadge = document.getElementById("liveness-badge");
const dispLiveScore = document.getElementById("disp-live-score");
const dispReplayProb = document.getElementById("disp-replay-prob");
const dispLiveConf = document.getElementById("disp-live-conf");
const livenessTimelineSvgContainer = document.getElementById("liveness-timeline-svg-container");

// Telemetry Elements
const dispConnection = document.getElementById("disp-connection");
const dispAudio = document.getElementById("disp-audio");
const dispSampleRate = document.getElementById("disp-sample-rate");
const dispChunkDuration = document.getElementById("disp-chunk-duration");
const dispBufferSize = document.getElementById("disp-buffer-size");
const dispLatency = document.getElementById("disp-latency");
const dispPacketsRx = document.getElementById("disp-packets-rx");
const dispPacketsDrop = document.getElementById("disp-packets-drop");
const dispPacketsReorder = document.getElementById("disp-packets-reorder");
const dispWindowsCount = document.getElementById("disp-windows-count");
const eventLog = document.getElementById("event-log");

// Helper to log events
function logEvent(msg) {
  const li = document.createElement("li");
  li.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  eventLog.prepend(li);
  if (eventLog.children.length > 20) {
    eventLog.removeChild(eventLog.lastChild);
  }
}

// Connect to Phase 1 Ingestion WebSocket Endpoint
function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/api/v1/stream/ingest`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    wsStatus.className = "status-badge status-connected";
    statusLabel.textContent = "CONNECTED";
    dispConnection.textContent = "CONNECTED";
    dispConnection.className = "factor-val text-emerald";
    logEvent("Connected to WebSocket: /api/v1/stream/ingest");
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "TELEMETRY" && msg.data) {
        updateTelemetryUI(msg.data, msg.windows_count || 0);
      }
    } catch (e) {
      console.error("Error parsing telemetry message", e);
    }
  };

  ws.onclose = () => {
    wsStatus.className = "status-badge";
    statusLabel.textContent = "DISCONNECTED";
    dispConnection.textContent = "DISCONNECTED";
    dispConnection.className = "factor-val text-crimson";
    logEvent("Disconnected from server. Reconnecting in 2s...");
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

// Update Real-Time Telemetry Dashboard UI
function updateTelemetryUI(d, windowsCount) {
  dispConnection.textContent = d.connection_state || "CONNECTED";
  dispAudio.textContent = d.audio_state || "IDLE";
  dispSampleRate.textContent = `${d.sample_rate || 16000} Hz`;
  dispChunkDuration.textContent = `${d.chunk_duration_ms || 0} ms`;
  dispBufferSize.textContent = `${d.buffer_size_ms || 0} ms (${d.buffer_size_samples || 0} samples)`;
  dispLatency.textContent = `${d.latency_ms || 0} ms`;
  globalLatency.textContent = `Latency: ${d.latency_ms || 0} ms`;

  dispPacketsRx.textContent = d.packets_received || 0;
  dispPacketsDrop.textContent = d.packets_dropped || 0;
  dispPacketsReorder.textContent = d.packets_reordered || 0;
  dispWindowsCount.textContent = `${d.total_windows_generated || 0} Windows`;

  // Update Audio State Pill
  audioStatePill.textContent = d.audio_state;
  if (d.audio_state === "RECEIVING") {
    audioStatePill.className = "verdict-pill verdict-allow";
    dispAudio.className = "factor-val text-emerald";
  } else if (d.audio_state === "SILENCE") {
    audioStatePill.className = "verdict-pill verdict-warn";
    dispAudio.className = "factor-val text-amber";
  } else {
    audioStatePill.className = "verdict-pill verdict-idle";
    dispAudio.className = "factor-val text-muted";
  }

  // Update Phase 2 Voice Activity Meter Widget
  if (d.vad) {
    const prob = d.vad.speech_probability !== undefined ? d.vad.speech_probability : 0.0;
    const pct = Math.round(prob * 100);
    dispVadPct.textContent = `${pct}%`;
    vadMeterFill.style.width = `${pct}%`;

    if (d.vad.is_speech) {
      vadMeterFill.className = "vad-meter-fill state-active-speech";
      dispVadState.textContent = "SPEECH";
      dispVadState.className = "vad-state-text state-speech";
    } else {
      vadMeterFill.className = "vad-meter-fill";
      dispVadState.textContent = "SILENCE";
      dispVadState.className = "vad-state-text state-silence";
    }

    if (d.vad.start_time !== undefined && d.vad.start_time !== null) {
      dispVadTimestamps.textContent = `Interval: ${d.vad.start_time}s - ${d.vad.end_time || "live"}`;
    } else {
      dispVadTimestamps.textContent = `Interval: --`;
    }

    dispVadLatency.textContent = `VAD: ${d.vad.latency_ms || 0} ms`;
  }

  // Update Phase 3 Deepfake Analysis Widget & Timeline
  if (d.deepfake) {
    const df = d.deepfake;
    dispDfSpoof.textContent = `${Math.round((df.spoof_probability || 0) * 100)}%`;
    dispDfBonafide.textContent = `${Math.round((df.bonafide_probability || 0) * 100)}%`;
    dispDfConfidence.textContent = `${Math.round((df.confidence || 0) * 100)}%`;
    dispDfLatency.textContent = `${df.inference_latency_ms || 0} ms`;

    // Verdict Badge
    if (df.label === "spoof") {
      dfVerdictBadge.className = "verdict-pill verdict-block";
      dfVerdictBadge.textContent = "SPOOF";
    } else if (df.label === "bonafide") {
      dfVerdictBadge.className = "verdict-pill verdict-allow";
      dfVerdictBadge.textContent = "BONAFIDE";
    } else {
      dfVerdictBadge.className = "verdict-pill verdict-idle";
      dfVerdictBadge.textContent = "UNCERTAIN";
    }

    // Timeline list
    if (df.timeline && df.timeline.length > 0) {
      dfTimelineList.innerHTML = "";
      df.timeline.slice(-8).reverse().forEach(item => {
        const li = document.createElement("li");
        let cls = "timeline-item ";
        if (item.label === "BONAFIDE") cls += "timeline-bonafide";
        else if (item.label === "SPOOF") cls += "timeline-spoof";
        else if (item.label === "SUSPICIOUS") cls += "timeline-suspicious";
        else cls += "timeline-uncertain";
        li.className = cls;
        li.innerHTML = `<span><b>${item.time}</b> — ${item.label}</span><span>${Math.round((item.spoof_probability || 0) * 100)}% spoof</span>`;
        dfTimelineList.appendChild(li);
      });
    }
  }

  // Update Phase 5 Speaker Verification Widget
  if (d.speaker) {
    const spk = d.speaker;
    if (dispSpkId) dispSpkId.textContent = spk.speaker_id || "UNKNOWN";
    if (dispSpkSimilarity) dispSpkSimilarity.textContent = `${Math.round((spk.similarity || 0) * 100)}%`;
    if (dispSpkMatch) dispSpkMatch.textContent = spk.match ? "MATCH" : (spk.similarity > 0 ? "MISMATCH" : "--");
    if (dispSpkConfidence) dispSpkConfidence.textContent = `${Math.round((spk.confidence || 0) * 100)}%`;

    if (spkMatchBadge) {
      if (spk.match) {
        spkMatchBadge.className = "verdict-pill verdict-match";
        spkMatchBadge.textContent = "MATCH";
      } else if (spk.similarity > 0 && spk.speaker_id !== "UNKNOWN") {
        spkMatchBadge.className = "verdict-pill verdict-mismatch";
        spkMatchBadge.textContent = "MISMATCH";
      } else {
        spkMatchBadge.className = "verdict-pill verdict-idle";
        spkMatchBadge.textContent = "UNKNOWN";
      }
    }
  // Update Phase 6 Multi-Signal Risk Engine Widget
  if (d.risk) {
    const risk = d.risk;
    const score = risk.risk_score || 0;
    const level = risk.risk_level || "LOW";
    const action = risk.recommended_action || "ALLOW";

    if (dispRiskScore) {
      dispRiskScore.textContent = score;
      if (score >= 85) dispRiskScore.className = "risk-score-value text-crimson";
      else if (score >= 60) dispRiskScore.className = "risk-score-value text-amber";
      else if (score >= 35) dispRiskScore.className = "risk-score-value text-cyan";
      else dispRiskScore.className = "risk-score-value text-emerald";
    }

    if (riskMeterFill) {
      riskMeterFill.style.width = `${Math.min(100, Math.max(0, score))}%`;
    }

    if (dispRiskLevel) {
      dispRiskLevel.textContent = level;
      dispRiskLevel.className = `badge-risk-level badge-level-${level.toLowerCase()}`;
    }

    if (dispRiskAction) {
      dispRiskAction.textContent = action;
      dispRiskAction.className = `badge-risk-action badge-action-${action.toLowerCase()}`;
    }

    if (riskActionBadge) {
      riskActionBadge.textContent = action;
      riskActionBadge.className = `verdict-pill verdict-${action === "BLOCK" ? "block" : action === "WARN" ? "warn" : action === "CHALLENGE" ? "uncertain" : "allow"}`;
    }

    if (dispRiskSignalsCount) {
      const sigs = risk.signals || [];
      dispRiskSignalsCount.textContent = `${sigs.length} Signal${sigs.length === 1 ? "" : "s"}`;
    }

    if (riskContributingList) {
      riskContributingList.innerHTML = "";
      const contribs = risk.contributing_signals || [];
      if (contribs.length > 0) {
        contribs.forEach(c => {
          const li = document.createElement("li");
          const lower = c.toLowerCase();
          if (lower.includes("synthetic") || lower.includes("clone") || lower.includes("failed") || lower.includes("block")) {
            li.className = "signal-item-active";
          } else if (lower.includes("liveness") || lower.includes("mismatch") || lower.includes("confidence")) {
            li.className = "signal-item-warn";
          } else {
            li.className = "signal-nominal";
          }
          li.textContent = `✓ ${c}`;
          riskContributingList.appendChild(li);
        });
      } else {
        const li = document.createElement("li");
        li.className = "signal-nominal";
        li.textContent = "✓ No abnormal threat signals detected (nominal)";
        riskContributingList.appendChild(li);
      }
    }
  }

  // ─── Phase 9: Liveness & Acoustic Replay Analysis ───
  if (d.liveness && d.liveness.liveness_score !== undefined) {
    const live = d.liveness;
    const scorePct = Math.round((live.liveness_score || 0) * 100);
    const replayPct = Math.round((live.replay_probability || 0) * 100);
    const confPct = Math.round((live.confidence || 0) * 100);

    if (dispLiveScore) {
      dispLiveScore.textContent = `${scorePct}%`;
      if (scorePct >= 70) dispLiveScore.className = "df-metric-val text-emerald";
      else if (scorePct >= 45) dispLiveScore.className = "df-metric-val text-amber";
      else dispLiveScore.className = "df-metric-val text-red";
    }

    if (dispReplayProb) {
      dispReplayProb.textContent = `${replayPct}%`;
      if (replayPct >= 65) dispReplayProb.className = "df-metric-val text-crimson";
      else if (replayPct >= 40) dispReplayProb.className = "df-metric-val text-amber";
      else dispReplayProb.className = "df-metric-val text-emerald";
    }

    if (dispLiveConf) dispLiveConf.textContent = `${confPct}%`;

    if (livenessBadge) {
      if (replayPct >= 65) {
        livenessBadge.className = "verdict-pill verdict-block";
        livenessBadge.textContent = "REPLAY DETECTED";
      } else if (scorePct < 45) {
        livenessBadge.className = "verdict-pill verdict-warn";
        livenessBadge.textContent = "SYNTHETIC CADENCE";
      } else {
        livenessBadge.className = "verdict-pill verdict-bonafide";
        livenessBadge.textContent = "LIVE ACOUSTIC";
      }
    }

    if (live.timeline_svg && livenessTimelineSvgContainer) {
      livenessTimelineSvgContainer.innerHTML = live.timeline_svg;
    }
  }

  // Update VAD badge
  if (d.vad && d.vad.is_speech) {
    vadBadge.className = "vad-indicator vad-speech";
    vadText.textContent = `SPEECH (${(d.vad.speech_probability * 100).toFixed(0)}%, ${d.vad.rms_db}dB)`;
  } else if (d.vad) {
    vadBadge.className = "vad-indicator";
    vadText.textContent = `SILENCE (${d.vad.rms_db}dB)`;
  }

  if (windowsCount > 0) {
    logEvent(`⚡ Generated ${windowsCount} 2.0s Analysis Window(s)`);
  }

  // ─── Phase 7: Pipeline Performance HUD ───
  if (d.pipeline) {
    const lat = d.pipeline.latency || {};
    const met = d.pipeline.metrics || {};
    const dev = d.pipeline.device || {};

    const maxMs = 150; // latency budget for bar scaling

    const barUpdate = (barId, valId, ms) => {
      const bar = document.getElementById(barId);
      const val = document.getElementById(valId);
      if (bar && val) {
        const pct = Math.min(100, (ms / maxMs) * 100);
        bar.style.width = pct + "%";
        val.textContent = ms.toFixed(1) + " ms";
      }
    };

    barUpdate("bar-preprocess", "val-preprocess", lat.preprocess_ms || 0);
    barUpdate("bar-vad", "val-vad", lat.vad_ms || 0);
    barUpdate("bar-deepfake", "val-deepfake", lat.deepfake_ms || 0);
    barUpdate("bar-speaker", "val-speaker", lat.speaker_ms || 0);
    barUpdate("bar-liveness", "val-liveness", lat.liveness_ms || 0);
    barUpdate("bar-risk", "val-risk", lat.risk_engine_ms || 0);

    const dispE2E = document.getElementById("disp-e2e-latency");
    const dispInf = document.getElementById("disp-inference-latency");
    const dispQD = document.getElementById("disp-queue-depth");
    const dispDC = document.getElementById("disp-dropped-chunks");
    const dispGPU = document.getElementById("disp-gpu-status");
    const dispDev = document.getElementById("disp-device-name");

    if (dispE2E) dispE2E.textContent = (lat.end_to_end_ms || 0).toFixed(1) + " ms";
    if (dispInf) dispInf.textContent = (lat.total_inference_ms || 0).toFixed(1) + " ms";
    if (dispQD) dispQD.textContent = met.queue_depth || 0;
    if (dispDC) dispDC.textContent = met.dropped_chunks || 0;
    if (dispGPU) {
      dispGPU.textContent = met.is_gpu_enabled ? "ENABLED" : "CPU ONLY";
      dispGPU.className = `df-metric-val ${met.is_gpu_enabled ? "text-emerald" : "text-amber"}`;
    }
    if (dispDev) dispDev.textContent = met.device_name || dev.device_name || "--";
  }
}

// Microphone Capture (16kHz Mono 16-bit PCM)
async function toggleMicrophone() {
  if (isRecording) {
    stopRecording();
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, sampleRate: 16000 }
    });
    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });

    const source = audioContext.createMediaStreamSource(mediaStream);
    const bufferSize = 2048; // ~128ms chunks at 16kHz
    scriptProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1);

    scriptProcessor.onaudioprocess = (e) => {
      if (!isRecording || !ws || ws.readyState !== WebSocket.OPEN) return;
      const inputData = e.inputBuffer.getChannelData(0);

      drawOscilloscope(inputData);

      clientSequenceCounter++;
      sendBinaryChunk(clientSequenceCounter, inputData);
    };

    source.connect(scriptProcessor);
    scriptProcessor.connect(audioContext.destination);

    isRecording = true;
    btnToggleMic.className = "btn btn-warning";
    btnToggleMic.querySelector(".btn-text").textContent = "Stop Microphone";
    logEvent("Microphone active at 16000Hz. Streaming PCM chunks...");
  } catch (err) {
    alert("Microphone permission denied or device error: " + err.message);
  }
}

function stopRecording() {
  isRecording = false;
  if (scriptProcessor) scriptProcessor.disconnect();
  if (audioContext) audioContext.close();
  if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());

  btnToggleMic.className = "btn btn-primary";
  btnToggleMic.querySelector(".btn-text").textContent = "Start Microphone";
  logEvent("Microphone stopped.");
}

// Serialize into the standard 28-Byte Binary Header Protocol:
// [Magic 4B: 'VIGI'][Seq 8B][TS 8B][SampleRate 4B][Length 4B][16-bit PCM...]
function sendBinaryChunk(seq, floatArray) {
  const pcmByteLength = floatArray.length * 2;
  const totalLength = 28 + pcmByteLength;
  const buffer = new ArrayBuffer(totalLength);
  const view = new DataView(buffer);

  // Magic 'VIGI' = 0x56494749
  view.setUint8(0, 0x56);
  view.setUint8(1, 0x49);
  view.setUint8(2, 0x47);
  view.setUint8(3, 0x49);

  // Sequence ID (64-bit uint)
  view.setBigUint64(4, BigInt(seq), false);

  // Timestamp ms (64-bit uint)
  view.setBigUint64(12, BigInt(Date.now()), false);

  // Sample Rate (32-bit uint: 16000)
  view.setUint32(20, 16000, false);

  // Payload Length (32-bit uint)
  view.setUint32(24, pcmByteLength, false);

  // PCM 16-bit samples (little endian)
  let offset = 28;
  for (let i = 0; i < floatArray.length; i++) {
    let s = Math.max(-1, Math.min(1, floatArray[i]));
    let val = s < 0 ? s * 0x8000 : s * 0x7FFF;
    view.setInt16(offset, val, true); // little-endian PCM
    offset += 2;
  }

  ws.send(buffer);
}

// Canvas Waveform Visualizer
function drawOscilloscope(data) {
  canvasCtx.fillStyle = "rgba(10, 15, 25, 0.4)";
  canvasCtx.fillRect(0, 0, canvas.width, canvas.height);

  canvasCtx.lineWidth = 2;
  canvasCtx.strokeStyle = "#38bdf8";
  canvasCtx.beginPath();

  const sliceWidth = canvas.width / data.length;
  let x = 0;

  for (let i = 0; i < data.length; i++) {
    const v = data[i];
    const y = (v + 1) / 2 * canvas.height;
    if (i === 0) canvasCtx.moveTo(x, y);
    else canvasCtx.lineTo(x, y);
    x += sliceWidth;
  }
  canvasCtx.stroke();
}

// Interactive Simulators for Testing
document.getElementById("btn-sim-speech").addEventListener("click", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return alert("WebSocket disconnected!");
  logEvent("Injecting 1.0s voice speech burst (10 packets)...");

  for (let i = 1; i <= 10; i++) {
    setTimeout(() => {
      clientSequenceCounter++;
      const samples = new Float32Array(1600); // 100ms
      const f0 = 130;
      for (let j = 0; j < 1600; j++) {
        const t = (i * 1600 + j) / 16000;
        const env = 0.5 * (1.0 + Math.sin(2 * Math.PI * 3 * t));
        const pulse = (Math.sin(2 * Math.PI * f0 * t) > 0.8 ? 0.6 : -0.1);
        const formants = 0.3 * Math.sin(2 * Math.PI * 750 * t) + 0.2 * Math.sin(2 * Math.PI * 1200 * t);
        samples[j] = Math.max(-0.85, Math.min(0.85, (pulse + formants) * env));
      }
      sendBinaryChunk(clientSequenceCounter, samples);
      drawOscilloscope(samples);
    }, i * 100);
  }
});

document.getElementById("btn-sim-clone").addEventListener("click", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return alert("WebSocket disconnected!");
  logEvent("Injecting 2.0s AI Voice Clone burst with vocoder artifacts...");

  for (let i = 1; i <= 20; i++) {
    setTimeout(() => {
      clientSequenceCounter++;
      const samples = new Float32Array(1600); // 100ms
      const f0 = 130;
      for (let j = 0; j < 1600; j++) {
        const t = (i * 1600 + j) / 16000;
        const env = 0.5 * (1.0 + Math.sin(2 * Math.PI * 3.5 * t));
        // Incoherent phase randomization characteristic of neural vocoders
        let s = 0.0;
        for (let h = 1; h <= 6; h++) {
          s += (0.3 / h) * Math.sin(2 * Math.PI * f0 * h * t + (h * 1.7));
        }
        samples[j] = Math.max(-0.85, Math.min(0.85, s * env));
      }
      sendBinaryChunk(clientSequenceCounter, samples);
      drawOscilloscope(samples);
    }, i * 100);
  }
});

document.getElementById("btn-sim-drop").addEventListener("click", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return alert("WebSocket disconnected!");
  logEvent("Simulating packet drop: Jumping sequence by +15...");
  clientSequenceCounter += 15;
  const samples = new Float32Array(1600);
  for (let j = 0; j < 1600; j++) samples[j] = 0.4 * Math.sin(2 * Math.PI * 440 * (j / 16000));
  sendBinaryChunk(clientSequenceCounter, samples);
});

document.getElementById("btn-sim-reorder").addEventListener("click", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return alert("WebSocket disconnected!");
  logEvent("Simulating jitter reorder: Sending Seq 2 before Seq 1...");
  const samples1 = new Float32Array(1600);
  const samples2 = new Float32Array(1600);
  for (let j = 0; j < 1600; j++) {
    samples1[j] = 0.3 * Math.sin(2 * Math.PI * 300 * (j / 16000));
    samples2[j] = 0.3 * Math.sin(2 * Math.PI * 600 * (j / 16000));
  }

  const s1 = ++clientSequenceCounter;
  const s2 = ++clientSequenceCounter;

  // Send out-of-order: s2 first, then s1
  sendBinaryChunk(s2, samples2);
  setTimeout(() => sendBinaryChunk(s1, samples1), 50);
});

document.getElementById("btn-sim-silence").addEventListener("click", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return alert("WebSocket disconnected!");
  logEvent("Injecting pure silence chunks...");
  for (let i = 1; i <= 10; i++) {
    setTimeout(() => {
      clientSequenceCounter++;
      const silence = new Float32Array(1600);
      sendBinaryChunk(clientSequenceCounter, silence);
    }, i * 100);
  }
});

// Phase 6 Simulator: Targeted Voice Clone (Alice's enrolled profile + synthetic vocoder)
const btnSimTargetedClone = document.getElementById("btn-sim-targeted-clone");
if (btnSimTargetedClone) {
  btnSimTargetedClone.addEventListener("click", () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return alert("WebSocket disconnected!");
    logEvent("🚨 Injecting TARGETED VOICE CLONE (Alice's 130Hz voiceprint + synthetic phase jitter)...");

    for (let i = 1; i <= 16; i++) {
      setTimeout(() => {
        clientSequenceCounter++;
        const chunk = new Float32Array(2000);
        for (let j = 0; j < chunk.length; j++) {
          const t = (i * 2000 + j) / 16000;
          // Alice's pitch (130Hz) mixed with high-frequency vocoder phase incoherence
          const vocalTract = 0.5 * Math.sin(2 * Math.PI * 130 * t) + 0.3 * Math.sin(2 * Math.PI * 260 * t);
          const vocoderArtifact = 0.15 * Math.sin(2 * Math.PI * 3400 * t + Math.sin(t * 100));
          chunk[j] = vocalTract + vocoderArtifact;
        }
        sendBinaryChunk(clientSequenceCounter, chunk);
      }, i * 125);
    }
  });
}

// Phase 5 Simulator: Multi-Utterance Enrollment for Alice
const btnEnrollAlice = document.getElementById("btn-enroll-alice");
if (btnEnrollAlice) {
  btnEnrollAlice.addEventListener("click", async () => {
    logEvent("Generating 3 enrollment utterances for Alice (130Hz vocal harmonics)...");
    btnEnrollAlice.disabled = true;

    try {
      const utterancesB64 = [];
      const f0 = 130;
      for (let u = 0; u < 3; u++) {
        const samples = new Int16Array(16000); // 1.0s at 16kHz
        for (let j = 0; j < 16000; j++) {
          const t = j / 16000;
          const env = 0.5 * (1.0 + Math.sin(2 * Math.PI * 2 * t));
          const s = (0.5 * Math.sin(2 * Math.PI * (f0 + u * 2) * t) + 0.3 * Math.sin(2 * Math.PI * 260 * t)) * env;
          samples[j] = Math.round(Math.max(-1, Math.min(1, s)) * 32767);
        }
        // Base64 encode PCM
        const uint8 = new Uint8Array(samples.buffer);
        let binary = "";
        for (let b = 0; b < uint8.byteLength; b++) {
          binary += String.fromCharCode(uint8[b]);
        }
        utterancesB64.push(btoa(binary));
      }

      const res = await fetch("/api/v1/speaker/enroll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          speaker_id: "alice",
          name: "Alice Smith",
          utterances_base64: utterancesB64,
        }),
      });

      const data = await res.json();
      if (res.ok && data.success) {
        logEvent(`✅ Enrolled Alice: consistency ${Math.round(data.intra_speaker_consistency * 100)}% (3 utterances)`);
        btnEnrollAlice.className = "btn btn-primary";
        btnEnrollAlice.innerHTML = "<span>✅ Alice Enrolled</span>";
      } else {
        logEvent(`❌ Enrollment failed: ${data.detail || data.message || "error"}`);
      }
    } catch (err) {
      logEvent(`❌ Enrollment network error: ${err.message}`);
    } finally {
      btnEnrollAlice.disabled = false;
    }
  });
}

btnToggleMic.addEventListener("click", toggleMicrophone);

window.addEventListener("load", () => {
  canvas.width = canvas.parentElement.clientWidth;
  canvas.height = canvas.parentElement.clientHeight;
  connectWebSocket();
});
