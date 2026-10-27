export const CRISIS_LABELS = { vigilance: "Vigilance", eleve: "Risque élevé", urgence: "Urgence" };
export const CRISIS_RANK = { none: 0, vigilance: 1, eleve: 2, urgence: 3 };
export const isCrisis = (level) => Boolean(CRISIS_RANK[level]);
export const asList = (value) => (Array.isArray(value) ? value : []);
