export interface SecurityTelemetry {
  session_id?: string;
  policy_version?: string;
  connection_status: 'CONNECTED' | 'DISCONNECTED' | 'CONNECTING';
  call_status: 'MONITORING' | 'CHALLENGING' | 'WARNED' | 'BLOCKED';
  
  // Center Gauges
  voice_authenticity: number; // 0 - 100
  speaker_match: number;       // 0 - 100
  liveness: number;            // 0 - 100
  deepfake_probability: number; // 0 - 100
  risk_score: number;          // 0 - 100
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  action: 'ALLOW' | 'MONITOR' | 'CHALLENGE' | 'WARN' | 'BLOCK';
  confidence: number;          // 0 - 1

  // Meta & Telemetry
  latency_ms: number;
  model_version: string;
  vad_active: boolean;
  sample_rate: number;
  chunk_duration: string;

  // Threat signals
  threat_signals: string[];

  // Timeline events
  timeline: Array<{
    id: string;
    time: string;
    verdict: 'Genuine' | 'Suspicious' | 'Synthetic' | 'Critical';
    confidence: number;
    detail: string;
  }>;

  // Conversation Intelligence
  conversation: {
    intent: string;
    risk_signal: number;
    evidence: string;
  } | null;

  // Adaptive Challenge
  active_challenge?: {
    challenge_id: string;
    prompt: string;
    expires_in_sec: number;
    status: 'PENDING' | 'PASSED' | 'FAILED';
  } | null;
}
