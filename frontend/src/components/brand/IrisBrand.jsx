import './IrisBrand.css';

export default function IrisBrand() {
  return <span className="iris-wordmark" aria-label="Iris">
    <svg viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <path d="M20 32C5 25 3 13 10 12c6-1 10 10 10 20Z" fill="#92a794" />
      <path d="M20 32c15-7 17-19 10-20-6-1-10 10-10 20Z" fill="#647c6b" />
      <path d="M20 29C8 18 14 3 20 5c6-2 12 13 0 24Z" fill="#c3b5d8" />
      <path d="M20 29C17 19 17 11 20 6c3 5 3 13 0 23Z" fill="#9986b2" />
      <path d="M20 27v10" stroke="#657969" strokeWidth="2" strokeLinecap="round" />
    </svg>
    <span className="iris-wordmark-text" aria-hidden="true">iris<span className="iris-wordmark-dot">.</span></span>
  </span>;
}
