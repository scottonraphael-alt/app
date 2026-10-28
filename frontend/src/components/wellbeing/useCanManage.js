import { listTrainings } from "./wellbeingApi";

/** Vrai si l'utilisateur peut éditer (responsable ou coordinateur) : réutilise le drapeau `can_manage` des formations. */
export async function getMe() {
  const data = await listTrainings();
  return Boolean(data?.can_manage);
}
