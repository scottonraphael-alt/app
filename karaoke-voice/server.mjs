import http from 'node:http';
import crypto from 'node:crypto';
import {Client,GatewayIntentBits,ChannelType} from 'discord.js';
import {joinVoiceChannel,entersState,VoiceConnectionStatus,EndBehaviorType} from '@discordjs/voice';
import prism from 'prism-media';
import {features,FRAME_BYTES,HOP_BYTES} from './dsp.mjs';

const secret=process.env.KARAOKE_VOICE_SECRET||(process.env.APP_SESSION_SECRET?crypto.createHmac('sha256',process.env.APP_SESSION_SECRET).update('iris-karaoke-voice-v1').digest('hex'):'');
if(secret.length<32)throw new Error('KARAOKE_VOICE_SECRET doit contenir au moins 32 caractères.');
const token=process.env.KARAOKE_BOT_TOKEN||process.env.DISCORD_BOT_TOKEN;
const backend=process.env.KARAOKE_BACKEND_URL||'http://backend:8000/api/activity/karaoke';
const client=new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildVoiceStates]});
let active=null,starting=false;
const notice='🎤 **Karaoké · analyse vocale**\nOasisLink peut analyser le rythme et la hauteur de la voix des joueurs qui l’activent dans le karaoké. Aucun enregistrement vocal n’est conservé. Tu peux refuser ou retirer ton accord à tout moment dans « Score vocal ». Porte un casque pour éviter que la musique entre dans ton micro.';

function stopStreams(){
  if(!active)return;
  for(const stream of active.streams.values()){stream.opus.destroy();stream.decoder.destroy();}
  active.streams.clear();active.frames=[];
}
function stop(){
  if(!active)return;
  stopStreams();active.connection.destroy();active=null;
}
async function api(path,{method='GET',body}={}){
  const headers={Authorization:'Bearer '+secret};
  let text;
  if(body){text=JSON.stringify(body);const stamp=String(Date.now()/1000);headers['Content-Type']='application/json';headers['X-Karaoke-Time']=stamp;headers['X-Karaoke-Signature']=crypto.createHmac('sha256',secret).update(stamp+'.'+text).digest('hex');}
  const response=await fetch(backend+path,{method,body:text,headers,signal:AbortSignal.timeout(7000)});
  if(!response.ok)throw new Error('API karaoké indisponible ('+response.status+')');
  return response.json();
}
function subscribe(uid){
  if(!active||active.streams.has(uid)||!active.channel.members.has(uid))return;
  const session=active;
  const opus=session.connection.receiver.subscribe(uid,{end:{behavior:EndBehaviorType.Manual}});
  const decoder=new prism.opus.Decoder({rate:48000,channels:2,frameSize:960});
  session.streams.set(uid,{opus,decoder});
  let buffer=Buffer.alloc(0);
  const release=()=>{session.streams.delete(uid);opus.destroy();decoder.destroy();};
  opus.on('error',release);decoder.on('error',release);
  opus.pipe(decoder).on('data',chunk=>{
    if(active!==session||!session.allowed.has(uid))return;
    buffer=Buffer.concat([buffer,chunk]);
    while(buffer.length>=FRAME_BYTES){ // Overlapping 100 ms windows, one pitch frame every 50 ms
      const frame=buffer.subarray(0,FRAME_BYTES);buffer=buffer.subarray(HOP_BYTES);
      const seq=(session.sequence.get(uid)||0)+1;session.sequence.set(uid,seq);
      session.frames.push({uid,seq,at:Date.now()/1000,...features(frame)});
      if(session.frames.length>1000)session.frames.shift();
    }
  });
}
async function cycle(){
  try{
    const connected=active?.connection.state.status===VoiceConnectionStatus.Ready?active.id:'';
    const control=await api('/internal/voice/control?connected_id='+encodeURIComponent(connected));
    if(!active)return;
    const config=control.sessions.find(s=>s.id===active.id);
    if(!config){stop();return;}
    if(active.generation!==config.generation){stopStreams();active.sequence.clear();active.generation=config.generation;}
    active.allowed=new Set(config.active?config.consents:[]);
    for(const [uid,stream] of active.streams){if(!active.allowed.has(uid)||!active.channel.members.has(uid)){stream.opus.destroy();stream.decoder.destroy();active.streams.delete(uid);}}
    for(const uid of active.allowed)subscribe(uid);
    if(active.frames.length){const frames=active.frames.splice(0,1000);await api('/internal/voice/frames',{method:'POST',body:{id:active.id,generation:active.generation,sample_step:.05,frames}});}
  }catch(error){stopStreams();console.error(error.message);}
}
async function loop(){await cycle();setTimeout(loop,300);}

client.on('voiceStateUpdate',async(before,after)=>{
  if(!active)return;
  if(before.id===client.user.id&&after.channelId!==active.channel.id){stop();return;}
  if(after.channelId===active.channel.id&&before.channelId!==after.channelId&&!after.member.user.bot){
    try{await active.channel.send({content:`<@${after.id}>\n`+notice,allowedMentions:{parse:[],users:[after.id]}});}catch(error){stop();}
  }
});
const server=http.createServer(async(req,res)=>{
  const reply=(status,data)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
  if(req.headers.authorization!=='Bearer '+secret){reply(403,{error:'Service non autorisé.'});return;}
  if(req.method!=='POST'){reply(405,{error:'Méthode invalide.'});return;}
  let claimedStart=false;
  try{
    let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>10000)throw new Error('Requête trop volumineuse.');}
    const body=JSON.parse(raw);
    if(req.url==='/stop'){if(active&&active.id!==body.id)throw new Error('Session différente.');stop();reply(200,{status:'stopped'});return;}
    if(req.url!=='/start'){reply(404,{error:'Introuvable.'});return;}
    if(active||starting)throw new Error('OasisLink est déjà connecté.');
    starting=true;claimedStart=true;
    if(!client.isReady())throw new Error('Le bot est en cours de connexion.');
    if(String(body.guild_id)!==String(process.env.DISCORD_GUILD_ID))throw new Error('Serveur non autorisé.');
    const guild=await client.guilds.fetch(body.guild_id);
    const channelId=body.channel_id||guild.voiceStates.cache.get(body.actor_id)?.channelId;
    if(!channelId)throw new Error('Rejoins un salon vocal Discord pour activer les scores.');
    const channel=await guild.channels.fetch(channelId);
    if(channel?.type!==ChannelType.GuildVoice||!channel.members.has(body.actor_id))throw new Error('Rejoins ce salon vocal avant de connecter le bot.');
    if(guild.members.me.voice.channelId)throw new Error('OasisLink est déjà utilisé dans un salon vocal.');
    // Notice must be delivered BEFORE joining/receiving any participant audio.
    await channel.send({content:notice,allowedMentions:{parse:[]}});
    const connection=joinVoiceChannel({channelId:channel.id,guildId:guild.id,adapterCreator:guild.voiceAdapterCreator,selfDeaf:false,selfMute:true});
    try{await entersState(connection,VoiceConnectionStatus.Ready,20000);}catch(error){connection.destroy();throw error;}
    active={id:body.id,channel,connection,streams:new Map(),frames:[],sequence:new Map(),allowed:new Set(),generation:null};
    connection.on('error',()=>stop());
    connection.on(VoiceConnectionStatus.Disconnected,()=>stop());
    reply(200,{status:'connected',bot_id:client.user.id,channel_id:channel.id});
  }catch(error){reply(409,{error:error.message});}finally{if(claimedStart)starting=false;}
});
client.once('clientReady',()=>{server.listen(8091,'0.0.0.0');loop();});
for(const event of ['SIGINT','SIGTERM'])process.on(event,()=>{stop();server.close();client.destroy();process.exit(0);});
await client.login(token);
