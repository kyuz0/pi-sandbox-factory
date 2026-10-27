import { getAgentDir } from '@earendil-works/pi-coding-agent';
import { registerLocalModels } from '../scripts/local-models-command.mjs';

export default function (pi) {
  registerLocalModels(pi, { getAgentDir });
}
