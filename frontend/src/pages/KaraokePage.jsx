import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api,getErrorMessage} from '../api/client';
import KaraokeStage from './KaraokeStage';
import '../Casier.css';
export default function KaraokePage(){
 const [session,setSession]=useState(null),[error,setError]=useState('');
 useEffect(()=>{document.body.classList.add('casier-no-nav');return()=>document.body.classList.remove('casier-no-nav');},[]);
 useEffect(()=>{let live=true;api.post('/activity/karaoke/site-session').then(r=>{if(live)setSession({...r.data,apiRoot:api.defaults.baseURL});}).catch(e=>{if(live)setError(getErrorMessage(e));});return()=>{live=false;};},[]);
 if(error)return <main style={{padding:32}}><h1>Le salon musical</h1><p role="alert">{error}</p><Link to="/">Retour à Iris</Link></main>;
 if(!session)return <p role="status" style={{padding:32}}>Ouverture du salon musical…</p>;
 return <KaraokeStage session={session}/>;
}
