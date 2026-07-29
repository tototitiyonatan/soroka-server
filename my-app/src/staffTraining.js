export const TRAINING_OPTIONS = [
  'אחרי שלב א',
  'אחרי סבב מיון יולדות',
];

const TRAINING_SEPARATOR = '|';

export function parseTraining(value) {
  if (!value) return [];
  if (value.startsWith('[')) {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed.filter(Boolean) : [value];
    } catch {
      return [value];
    }
  }
  return value.split(TRAINING_SEPARATOR).filter(Boolean);
}

export function serializeTraining(selected) {
  if (!selected?.length) return null;
  return selected.join(TRAINING_SEPARATOR);
}

export function formatTrainingDisplay(value) {
  return parseTraining(value).join(', ');
}

export function toggleTrainingOption(value, option) {
  const selected = parseTraining(value);
  return selected.includes(option)
    ? selected.filter((item) => item !== option)
    : [...selected, option];
}
