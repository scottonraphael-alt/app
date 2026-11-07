import { useEffect, useState } from 'react';
import { karaokeRequest } from './KaraokeTools';

export default function BlindTestCategories({ session, style, decade, onChange, onLoading }) {
  const [options, setOptions] = useState(null);
  const [error, setError] = useState('');
  const [count, setCount] = useState(null);
  const [retry, setRetry] = useState(0);
  const token = session.videoToken, apiRoot = session.apiRoot;
  useEffect(() => {
    const controller = new AbortController();
    karaokeRequest({ videoToken: token, apiRoot }, '/catalog/categories', { signal: controller.signal })
      .then(setOptions).catch(exc => { if (!controller.signal.aborted) setError(exc.message); });
    return () => controller.abort();
  }, [token, apiRoot, retry]);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    setError(''); setCount(null);
    if (!style && !decade) { onLoading(false); return () => controller.abort(); }
    onLoading(true);
    const timer = setTimeout(() => {
      karaokeRequest({ videoToken: token, apiRoot }, '/catalog/category',
        { query: { style, decade }, signal: controller.signal })
        .then(data => { if (live) setCount(data.count); })
        .catch(exc => { if (live && !controller.signal.aborted) setError(exc.message); })
        .finally(() => { if (live) onLoading(false); });
    }, 250);
    return () => { live = false; clearTimeout(timer); controller.abort(); };
  }, [token, apiRoot, style, decade, retry, onLoading]);
  return <fieldset style={{ border: '1px solid #ffffff30', borderRadius: 12, padding: 12, display: 'grid', gap: 10 }}>
    <legend>Catégories Deezer</legend>
    <label>Style musical
      <select aria-label="Style musical Deezer" value={style}
        onChange={event => onChange({ style: event.target.value, decade })}
        style={{ width: '100%', padding: 8, borderRadius: 8 }}>
        <option value="">Tous les styles</option>
        {(options?.styles || []).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
    </label>
    <label>Décennie
      <select aria-label="Décennie Deezer" value={decade}
        onChange={event => onChange({ style, decade: event.target.value })}
        style={{ width: '100%', padding: 8, borderRadius: 8 }}>
        <option value="">Toutes les décennies</option>
        {(options?.decades || []).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
    </label>
    <small>Sélections issues de playlists thématiques Deezer. Style et décennie peuvent être combinés.</small>
    {(style || decade) && count === null && !error && <p role="status">Chargement de la sélection Deezer…</p>}
    {count !== null && <p role="status">{count ? `${count} extraits dans cette sélection.` : 'Aucun extrait pour cette combinaison. Change de style ou de décennie.'}</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>Réessayer</button></p>}
  </fieldset>;
}
