import { greetingFor } from "./homeUtils";

export default function HomeGreeting({ pseudo, summary }) {
  return (
    <div className="hm-greeting" data-testid="home-greeting">
      <p className="hm-greeting-line">
        {greetingFor()}, <strong>{pseudo}</strong>
      </p>
      {summary && <p className="hm-greeting-summary" aria-live="polite">{summary}</p>}
    </div>
  );
}
