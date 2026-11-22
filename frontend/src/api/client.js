import axios from "axios";


const backendUrl = process.env.REACT_APP_BACKEND_URL;


export const api = axios.create({
  baseURL: `${backendUrl}/api`,
  withCredentials: true,
});


const fallbackMessage = "Une erreur est survenue. Réessayez.";
const detailMessage = (detail) => {
  if (typeof detail === "string") return detail.trim();
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    return [detail.message, detail.msg].find(value => typeof value === "string" && value.trim()) || "";
  }
  return "";
};

export const getErrorMessage = (error) => {
  const detail = error?.response?.data?.detail;
  const message = Array.isArray(detail)
    ? detail.map(detailMessage).filter(Boolean).join("\n")
    : detailMessage(detail);
  return message || fallbackMessage;
};
