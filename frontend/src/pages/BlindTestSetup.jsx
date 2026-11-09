import BlindTestCategories from './BlindTestCategories';
export default function BlindTestSetup({session,settings,setSettings,library,plays,setPlays,starting,setStarting,categoryLoading,setCategoryLoading,connected,send,setNotice}){
 const previews=library.filter(song=>song.preview).length;
 return (
            <section className="og-setup" aria-label="Préparer un blind test">
              <div style={{ fontWeight: 800 }}>🎯 Lancer un blind test</div>
              <label style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                Morceaux
                <select
                  value={settings.pool}
                  style={{ padding: 6, borderRadius: 8, maxWidth: 260 }}
                  onChange={(event) => {
                    if (event.currentTarget.value === "local") setCategoryLoading(false);
                    setSettings({ ...settings, pool: event.currentTarget.value, ...(event.currentTarget.value === "local" ? { style: "", decade: "" } : {}) });
                  }}
                >
                  <option value="all">Tout ({library.length})</option>
                  <option value="local">Mes fichiers ({library.length-previews})</option>
                  <option value="preview">Catalogue Deezer ({previews})</option>
                </select>
              </label>
              {settings.pool !== "local" && <BlindTestCategories session={session} style={settings.style} decade={settings.decade}
                onLoading={setCategoryLoading} onChange={selection => {
                  setCategoryLoading(Boolean(selection.style || selection.decade));
                  setSettings(current => ({ ...current, ...selection, pool: "preview" }));
                }} />}
              <label style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                Nombre de manches
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={settings.rounds}
                  style={{ width: 80, padding: 6, borderRadius: 8 }}
                  onChange={(event) => setSettings({ ...settings, rounds: Number(event.currentTarget.value) })}
                />
              </label>
              <label style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                Durée d'une manche (s)
                <input
                  type="number"
                  min="5"
                  max="90"
                  value={settings.seconds}
                  style={{ width: 80, padding: 6, borderRadius: 8 }}
                  onChange={(event) => setSettings({ ...settings, seconds: Number(event.currentTarget.value) })}
                />
              </label>
              {settings.pool !== "local" && settings.seconds > 28 && (
                <div style={{ fontSize: 12, opacity: 0.7 }}>Les extraits du catalogue durent 30 s : au-delà de ~28 s, la musique s'arrête avant la fin de la manche.</div>
              )}
              <label style={{ fontSize: 14, display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={plays} onChange={(event) => setPlays(event.target.checked)} />
                Je participe aussi
              </label>
              <button
                type="button"
                disabled={starting || categoryLoading || !connected}
                onClick={() => {
                  setStarting(true);
                  setNotice("");
                  send({ type: "bt_start", ...settings });
                }}
              >
                {starting ? "Préparation de la partie…" : categoryLoading ? "Chargement de la sélection…" : "Lancer la partie"}
              </button>
            </section>);
}
