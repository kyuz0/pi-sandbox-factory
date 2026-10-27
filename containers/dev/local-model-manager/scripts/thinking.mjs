// Source revisions and engine/template semantics: docs/thinking-research.md.
const levels = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
const map = values => Object.fromEntries(levels.map(level => [level, values[level] ?? null]));
const effortCompat = { supportsReasoningEffort: true, thinkingFormat: 'openai' };
const templateCompat = {
  supportsReasoningEffort: false, thinkingFormat: 'chat-template',
  chatTemplateKwargs: {
    enable_thinking: { $var: 'thinking.enabled' },
    preserve_thinking: true,
    reasoning_effort: { $var: 'thinking.effort', omitWhenOff: true },
  },
};
const qwen = map({ off: 'none', low: 'low', medium: 'medium', xhigh: 'xhigh' });
const highMax = map({ off: 'none', high: 'high', max: 'max' });
const profile = (thinkingLevelMap, compat) => ({ reasoning: true, thinkingLevelMap, compat });

export const thinkingProfiles = Object.freeze({
  disabled: { reasoning: false },
  'dwarfstar-qwen': profile(map({ off: 'none', low: 'low', medium: 'medium', xhigh: 'high' }), templateCompat),
  'dwarfstar-deepseek-v4': profile(highMax, effortCompat),
  'dwarfstar-deepseek41': profile(map({ off: 'none', low: 'low', medium: 'medium', high: 'high', max: 'max' }), effortCompat),
  'gufo-qwen': profile(qwen, templateCompat),
  'gufo-deepseek-v4': profile(map({ off: 'none', low: 'low', high: 'high', max: 'max' }), templateCompat),
  'llama-qwen': profile(qwen, templateCompat),
  'llama-thinking-toggle': profile(map({ off: 'none', high: 'high' }), {
    supportsReasoningEffort: false, thinkingFormat: 'chat-template',
    chatTemplateKwargs: { enable_thinking: { $var: 'thinking.enabled' } },
  }),
  'openai-effort': profile(map({ off: 'none', low: 'low', medium: 'medium', high: 'high', max: 'max' }), effortCompat),
});

export function validateThinkingOverrides(value = []) {
  if (!Array.isArray(value) || value.length > 256) throw new Error('thinkingOverrides must be an array of at most 256 entries');
  const seen = new Set();
  return value.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).some(key => !['endpoint', 'model', 'profile', 'thinkingLevelMap'].includes(key))) throw new Error('Invalid thinking override fields');
    const url = new URL(item.endpoint);
    if (url.protocol !== 'http:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash || !((url.hostname === 'local-model.internal') || url.hostname === 'localhost' || url.hostname === '[::1]' || /^127\.(?:\d{1,3}\.){2}\d{1,3}$/.test(url.hostname))) throw new Error('Thinking override endpoint must be a loopback HTTP origin or http://local-model.internal:<configured-port>');
    if (typeof item.model !== 'string' || !item.model.trim()) throw new Error('Thinking override needs an exact model ID');
    if (!Object.hasOwn(thinkingProfiles, item.profile)) throw new Error(`Unknown thinking profile: ${item.profile}`);
    const key = JSON.stringify([url.origin, item.model]);
    if (seen.has(key)) throw new Error('Duplicate endpoint/model thinking override');
    seen.add(key);
    if (item.thinkingLevelMap !== undefined) {
      const m = item.thinkingLevelMap;
      if (!m || typeof m !== 'object' || Array.isArray(m) || !Object.keys(m).length || Object.entries(m).some(([k, v]) => !levels.includes(k) || v !== null && (typeof v !== 'string' || !v.length || v.length > 128))) throw new Error('Invalid thinkingLevelMap: use Pi levels and string/null values');
      if (item.profile === 'disabled' || !Object.values(m).some(v => typeof v === 'string')) throw new Error('Thinking override must leave a supported level');
    }
    return { ...structuredClone(item), endpoint: url.origin };
  });
}

export function discoverThinking(model, props, singleModel) {
  const advertised = Array.isArray(model.supported_parameters) && model.supported_parameters.includes('reasoning_effort');
  const caps = singleModel ? props?.chat_template_caps : undefined;
  const engine = model.owned_by === 'ds4.c' ? 'dwarfstar' : model.owned_by === 'gufo' ? 'gufo' :
    model.owned_by === 'llamacpp' || model.owned_by === 'llama.cpp' || singleModel && typeof props?.chat_template === 'string' ? 'llama' : null;
  // This is a user-requested family default, not a discovered capability. A
  // served display name (DwarfStar's loaded GGUF name) takes priority over aliases.
  const name = (typeof model.name === 'string' && model.name || model.id).toLowerCase().replace(/\s+/g, '-');
  const qwen38 = /qwen[._-]?3[._-]8(?:[^0-9]|$)/.test(name);
  const deepseek41 = /deepseek[._-]?v?4[._-]1(?:[^0-9]|$)/.test(name);
  const deepseek4 = !deepseek41 && /deepseek[._-]?v?4(?:[^0-9]|$)/.test(name);
  let selected = null;
  if (qwen38 && engine) selected = `${engine}-qwen`;
  else if (engine === 'dwarfstar' && advertised && deepseek41) selected = 'dwarfstar-deepseek41';
  else if (engine === 'dwarfstar' && advertised && deepseek4) selected = 'dwarfstar-deepseek-v4';
  else if (engine === 'gufo' && deepseek4) selected = 'gufo-deepseek-v4';
  else if (engine === 'llama' && /qwen[._-]?3[-_]\d+(?:\.\d+)?b(?:[^a-z0-9]|$)/.test(name) && !/instruct|thinking|coder|2507/.test(name)) selected = 'llama-thinking-toggle';
  if (selected) return {
    support: advertised ? true : null,
    profile: selected,
    evidence: `${engine} endpoint metadata + family default from served name; source-backed controls, deployed build/template unverified`,
    warning: 'Using an engine/model-family thinking default; deployed build/template is unverified. Existing custom settings or an exact endpoint/model override take precedence.',
  };
  return {
    support: advertised || caps?.supports_reasoning_effort === true ? true : null,
    profile: null,
    evidence: advertised ? '/v1/models.supported_parameters.reasoning_effort; accepted values unknown' : caps?.supports_reasoning_effort === true ? '/props.chat_template_caps.supports_reasoning_effort; accepted values unknown' : 'unknown; no verified thinking controls',
    warning: 'Thinking controls/accepted levels are unknown; no family default applied. Set an exact endpoint/model thinking override if needed.',
  };
}

export function thinkingConfig(name, customMap, contextWindow) {
  if (!Object.hasOwn(thinkingProfiles, name)) throw new Error(`Unknown thinking profile: ${name}`);
  const result = structuredClone(thinkingProfiles[name]);
  // DwarfStar V4 falls back to high below its Think Max context threshold.
  if (name === 'dwarfstar-deepseek-v4' && contextWindow < 393216) result.thinkingLevelMap.max = null;
  if (customMap) result.thinkingLevelMap = map(customMap);
  return result;
}

const thinkingCompatKeys = ['thinkingFormat', 'supportsReasoningEffort', 'chatTemplateKwargs', 'chatTemplateArgs', 'thinkingTokenBudgetField', 'supportsThinkingTokenBudget'];
export function hasExplicitThinking(model, provider) {
  return model && (model.reasoning !== undefined || model.thinkingLevelMap !== undefined || thinkingCompatKeys.some(k => model.compat?.[k] !== undefined)) ||
    thinkingCompatKeys.filter(k => k !== 'supportsReasoningEffort').some(k => provider?.compat?.[k] !== undefined) || provider?.compat?.supportsReasoningEffort === true;
}

export function applyThinking(model, settings) {
  if (!settings.reasoning) {
    const next = { ...model, reasoning: false };
    delete next.thinkingLevelMap;
    if (next.compat) {
      next.compat = { ...next.compat };
      for (const key of thinkingCompatKeys) delete next.compat[key];
    }
    return next;
  }
  // Model-level controls override inherited provider defaults without changing
  // the endpoint's other models or unrelated compatibility/customization.
  const compat = { ...model.compat };
  for (const key of thinkingCompatKeys) delete compat[key];
  return { ...model, ...settings, compat: { ...compat, ...settings.compat } };
}
