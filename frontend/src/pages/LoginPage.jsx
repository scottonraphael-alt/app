import { useEffect, useState } from "react";
import { AlertTriangle, ArrowUpRight, ShieldCheck } from "lucide-react";
import logo from "../assets/logo.png";
import "./Login.css";

// Le backend ne renvoie qu'un code : le texte affiché vient toujours d'ici.
const AUTH_ERROR_MESSAGES = {
  state_expired: "Session expirée, réessayez.",
  oauth_refused: "La connexion Discord a été refusée. Réessayez.",
  not_in_guild: "Votre compte Discord ne fait pas partie du serveur Iris.",
  missing_role: "Votre compte Discord ne possède pas un rôle autorisé pour Iris.",
  unavailable: "Connexion momentanément indisponible. Réessayez plus tard.",
};
const DEFAULT_AUTH_ERROR = "La connexion a échoué. Réessayez.";


export default function LoginPage() {
  const backendUrl = process.env.REACT_APP_BACKEND_URL;
  const [authError, setAuthError] = useState(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const error = params.get("auth_error");
    if (error) {
      setAuthError(
        Object.prototype.hasOwnProperty.call(AUTH_ERROR_MESSAGES, error)
          ? AUTH_ERROR_MESSAGES[error]
          : DEFAULT_AUTH_ERROR
      );
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  return (
    <main className="lg-page" data-testid="login-page">
      <section className="lg-card">
        <img className="lg-logo" src={logo} alt="Iris" data-testid="login-iris-logo" />
        <p className="lg-eyebrow">Iris · Espace de gestion</p>
        <h1>Bienvenue sur Iris</h1>
        <p className="lg-lead">
          L’espace de travail du Staff de L’Oasis, pour centraliser les tâches et accompagner avec soin.
        </p>

        {authError && (
          <div className="lg-error" role="alert" data-testid="auth-error-message">
            <AlertTriangle size={18} />
            <p>{authError}</p>
          </div>
        )}

        <a
          className="lg-button"
          href={`${backendUrl}/api/auth/discord/login`}
          data-testid="discord-login-button"
        >
          Se connecter avec Discord <ArrowUpRight size={18} />
        </a>
        <p className="lg-note">
          <ShieldCheck size={14} /> Accès réservé aux membres du Staff ayant un rôle autorisé.
        </p>
      </section>
      <footer className="lg-footer" data-testid="login-footer">IRIS · ESPACE CONFIDENTIEL · L'OASIS 2026</footer>
    </main>
  );
}
