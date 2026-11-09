import {useEffect,useState} from 'react';
import {DiscordSDK} from '@discord/embedded-app-sdk';
import KaraokeStage from './KaraokeStage';
import './OasisGame.css';
const PROXY='/.proxy/backend/api';
export default function OasisGamePage(){
 const [session,setSession]=useState(null),[error,setError]=useState('');
 useEffect(()=>{
  let cancelled=false;
  (async()=>{
   const configResponse=await fetch(PROXY+'/games/config');
   if(!configResponse.ok)throw new Error('Configuration OasisGame indisponible.');
   const config=await configResponse.json();
   if(!config.configured)throw new Error('L’application Discord OasisGame doit encore être créée et configurée sur le serveur.');
   const sdk=new DiscordSDK(config.client_id);await sdk.ready();
   const {code}=await sdk.commands.authorize({client_id:config.client_id,response_type:'code',state:'',prompt:'none',scope:['identify','guilds.members.read','rpc.activities.write']});
   const response=await fetch(PROXY+'/games/token',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,guild_id:sdk.guildId,instance_id:sdk.instanceId,channel_id:sdk.channelId})});
   const data=await response.json();
   if(!response.ok)throw new Error(data.detail||'Connexion à OasisGame refusée.');
   await sdk.commands.authenticate({access_token:data.access_token});
   try{await sdk.commands.setActivity({activity:{type:0,details:'Choisit un jeu',state:'OasisGame',instance:true}});}catch{/* Presence is optional. */}
   if(!cancelled)setSession({videoToken:data.video_token,instanceId:data.instance_id,userId:data.user_id,userName:data.user_name,canControl:data.can_control,games:true,channelId:sdk.channelId,guildId:sdk.guildId,karaokeChannelId:data.karaoke_channel_id,apiRoot:PROXY});
  })().catch(e=>{if(!cancelled)setError(e.message);});
  return()=>{cancelled=true;};
 },[]);
 if(error)return <main className="og-boot"><h1>OasisGame</h1><p role="alert">{error}</p><button onClick={()=>window.location.reload()}>Réessayer</button></main>;
 if(!session)return <main className="og-boot"><h1>OasisGame</h1><p role="status">Ouverture du salon de jeux…</p></main>;
 return <KaraokeStage session={session}/>;
}
