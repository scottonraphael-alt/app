import {useCallback,useEffect,useRef,useState} from 'react';
import {Film,HardDrive,RefreshCw,Trash2,Upload,Video} from 'lucide-react';
import {api,getErrorMessage} from '../api/client';
import './ActivityVideoAdminPage.css';

const CHUNK_BYTES=8*1024*1024;
const formatBytes=value=>{
  if(!Number.isFinite(value)||value<0)return '—';
  if(value<1024)return `${value} o`;
  const units=['Ko','Mo','Go','To'];let amount=value/1024,index=0;
  while(amount>=1024&&index<units.length-1){amount/=1024;index+=1;}
  return `${amount.toLocaleString('fr-FR',{maximumFractionDigits:1})} ${units[index]}`;
};

export default function ActivityVideoAdminPage(){
  const [storage,setStorage]=useState(null),[selected,setSelected]=useState(null),[progress,setProgress]=useState(0);
  const [loading,setLoading]=useState(true),[uploading,setUploading]=useState(false),[deleting,setDeleting]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const input=useRef(null);
  const refresh=useCallback(async()=>{
    setError('');
    try{const response=await api.get('/activity/admin/storage');setStorage(response.data);}
    catch(err){setError(getErrorMessage(err));}
    finally{setLoading(false);}
  },[]);
  useEffect(()=>{refresh();},[refresh]);

  async function upload(){
    if(!selected||uploading)return;
    setUploading(true);setProgress(0);setError('');setNotice('');
    let uploadId=null;
    try{
      const started=await api.post('/activity/admin/uploads',{filename:selected.name,size:selected.size});
      uploadId=started.data.upload_id;
      let offset=0;
      while(offset<selected.size){
        const end=Math.min(offset+Math.min(CHUNK_BYTES,started.data.chunk_bytes||CHUNK_BYTES),selected.size);
        const chunk=selected.slice(offset,end);
        const response=await api.put(`/activity/admin/uploads/${uploadId}`,chunk,{headers:{'Content-Type':'application/octet-stream','X-Upload-Offset':String(offset)}});
        offset=response.data.offset;
        setProgress(Math.min(100,Math.round(offset/selected.size*100)));
      }
      const completed=await api.post(`/activity/admin/uploads/${uploadId}/complete`);
      uploadId=null;
      setNotice(`${completed.data.name} est disponible dans CinéStream.`);
      setSelected(null);setProgress(100);
      if(input.current)input.current.value='';
      await refresh();
    }catch(err){
      if(uploadId)try{await api.delete(`/activity/admin/uploads/${uploadId}`);}catch{/* expiration automatique si le réseau est indisponible */}
      setError(getErrorMessage(err));
    }finally{setUploading(false);}
  }

  async function removeVideo(video){
    if(deleting||uploading)return;
    if(!window.confirm(`Supprimer « ${video.title} » du catalogue CinéStream ?`))return;
    setDeleting(video.name);setError('');setNotice('');
    try{
      await api.delete('/activity/admin/videos',{params:{filename:video.name}});
      setNotice(`${video.title} a été supprimé du catalogue.`);
      await refresh();
    }catch(err){setError(getErrorMessage(err));}
    finally{setDeleting('');}
  }

  const safeBytes=Math.max(0,storage?.safe_upload_bytes??0);
  return <main className="av-page">
    <header className="av-header">
      <div><p className="av-eyebrow">ESPACE STAFF · DISCORD</p><h1>Films de CinéStream</h1><p>Ajoute ou supprime les vidéos du catalogue et surveille l’espace disponible sur le serveur.</p></div>
      <button className="av-button" onClick={refresh} disabled={loading||uploading}><RefreshCw size={16}/>Actualiser</button>
    </header>
    {error&&<div className="av-alert" role="alert">{error}</div>}{notice&&<div className="av-notice" role="status">{notice}</div>}
    <section className="av-storage-grid" aria-label="Espace disque">
      <article data-iris-reveal="card" className="av-card av-space-card"><span className="av-icon"><HardDrive size={20}/></span><div><p>Espace libre sur le serveur</p><strong>{loading?'Chargement…':formatBytes(storage?.free_bytes)}</strong><small>Capacité totale : {formatBytes(storage?.total_bytes)} · utilisée : {formatBytes(storage?.used_bytes)}</small></div></article>
      <article data-iris-reveal="card" className="av-card av-space-card"><span className="av-icon"><Upload size={20}/></span><div><p>Disponible pour un nouvel envoi</p><strong>{loading?'Chargement…':formatBytes(safeBytes)}</strong><small>Une réserve de {formatBytes(storage?.reserve_bytes)} est conservée pour le serveur.</small></div></article>
      <article data-iris-reveal="card" className="av-card av-space-card"><span className="av-icon"><Film size={20}/></span><div><p>Catalogue CinéStream</p><strong>{loading?'…':`${storage?.video_count??0} vidéo(s)`}</strong><small>{formatBytes(storage?.video_bytes)} occupés par les films.</small></div></article>
    </section>

    <section data-iris-reveal="card" className="av-card av-upload-card">
      <div className="av-section-heading"><span className="av-icon"><Video size={20}/></span><div><h2>Ajouter un film</h2><p>Formats MP4 et WebM. L’envoi se fait par blocs pour accepter les gros fichiers sans saturer la mémoire du serveur.</p></div></div>
      <label className="av-file-picker">Fichier vidéo<input ref={input} type="file" accept="video/mp4,video/webm,.mp4,.webm" disabled={uploading} onChange={event=>{setSelected(event.target.files?.[0]||null);setError('');setNotice('');setProgress(0);}}/></label>
      {selected&&<div className="av-selected"><span>{selected.name}</span><small>{formatBytes(selected.size)}</small></div>}
      {selected&&selected.size>safeBytes&&<p className="av-inline-alert">Ce fichier dépasse l’espace disponible après conservation de la réserve serveur.</p>}
      {uploading&&<div className="av-progress"><div><span>Envoi en cours</span><strong>{progress}%</strong></div><progress max="100" value={progress}>{progress}%</progress></div>}
      <button className="av-button av-primary" onClick={upload} disabled={!selected||uploading||loading||selected.size>safeBytes}><Upload size={16}/>{uploading?'Envoi…':'Téléverser la vidéo'}</button>
    </section>

    <section data-iris-reveal="card" className="av-card av-library">
      <div className="av-section-heading"><span className="av-icon"><Film size={20}/></span><div><h2>Vidéos disponibles</h2><p>Ces fichiers apparaissent dans le sélecteur de films de CinéStream.</p></div></div>
      {loading?<p className="av-empty">Lecture du catalogue…</p>:storage?.videos?.length?<ul>{storage.videos.map(video=><li key={video.name}><span className="av-film-title">{video.title}{storage.current_video===video.name&&<small className="av-current">En lecture</small>}</span><small>{formatBytes(video.size)}</small><button className="av-delete" type="button" aria-label={`Supprimer ${video.title}`} title="Supprimer le film" disabled={Boolean(deleting)||uploading} onClick={()=>removeVideo(video)}><Trash2 size={16}/>{deleting===video.name?'Suppression…':'Supprimer'}</button></li>)}</ul>:<p className="av-empty">Aucun film vidéo dans le catalogue.</p>}
    </section>
  </main>;
}
