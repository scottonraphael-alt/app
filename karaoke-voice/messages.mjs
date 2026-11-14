/** Components V2 panels; text only, no consent controls outside the Activity. */
export function vocalNotice(memberId=null){
  const intro=memberId?`Bienvenue <@${memberId}> ! Installe-toi, la scène est à toi.`:'Installe-toi, choisis ta chanson et profite du moment.';
  return {
    flags:32768,
    allowedMentions:{parse:[],...(memberId?{users:[memberId]}:{})},
    components:[{type:17,accent_color:0xE69DC5,components:[
      {type:10,content:'# 🎤 Ta voix, ton rythme\n### Un moment à partager, un score si tu en as envie.'},
      {type:10,content:intro},
      {type:14,divider:true,spacing:1},
      {type:10,content:'### ✨ Le score vocal\nOasisLink peut estimer la **justesse** et le **rythme** de ta voix pendant la chanson.'},
      {type:10,content:'### 🔒 Tu gardes la main\nL’analyse est **facultative** : active-la dans l’activité avec **« Activer les scores »**. Tu peux refuser ou retirer ton accord à tout moment avec **« Désactiver les scores »**.\n**Aucun enregistrement vocal n’est conservé.**'},
      {type:14,divider:true,spacing:1},
      {type:10,content:'🎧 **Le petit conseil**\nPorte un casque pour que la musique ne repasse pas dans ton micro.'},
      {type:10,content:'-# ✦ OasisGame · Chante à ton rythme, sans obligation de score.'},
    ]}],
  };
}
