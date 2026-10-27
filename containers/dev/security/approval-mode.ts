// Manual/off modes retain the boundary broker contract without a model call.
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { BOUNDARY_BROKER_SERVICE_KEY } from '@erichll/pi-auto-review/broker';

export default function approvalMode(pi: ExtensionAPI) {
  const mode = process.env.SANDBOX_APPROVAL_MODE;
  if (mode !== 'manual' && mode !== 'off') throw new Error('Invalid approval mode');
  const target = globalThis as Record<symbol, unknown>;
  if (target[BOUNDARY_BROKER_SERVICE_KEY]) throw new Error('Duplicate approval broker');
  const service = {
    async review() {
      const rationale = mode === 'manual' ? 'Human approval is required for this boundary request.'
        : 'Approval prompts are disabled; access beyond the inner sandbox is refused.';
      const review = { outcome: mode === 'manual' ? 'defer' : 'deny', riskLevel: 'medium', userAuthorization: 'unknown', rationale };
      return mode === 'manual' ? { kind: 'defer', review }
        : { kind: 'deny', review, circuitBreakerTripped: false, recoveryCommand: false };
    },
    consumeGrant() { return false; },
  };
  target[BOUNDARY_BROKER_SERVICE_KEY] = service;
  pi.on('session_shutdown', () => {
    if (target[BOUNDARY_BROKER_SERVICE_KEY] === service) delete target[BOUNDARY_BROKER_SERVICE_KEY];
  });
}
