const match_me = "妑헰ᛙ쒇倈횛腫Ð闺䪬ᥰ只䳽촳ꣽᨒ셆泎ꐖ楻䳔ἲ殨ꔆԡㄤក꨹䊩㴰⒟藯뭳죘㺷빡眙汄ጝফ꛵꿍쾗䤏ޥө쵺蛽調㞗䛸C窥䰙ࠃᇲ闲㾡颖癡꾨嬻戩ࣜ㐪蕞ꪵ㿩킡㢠鄒嵉荍뻏䟀૫❖ꨤ᭳硼⫎ம.constructor" 
const regex = /[_$A-Z\xA0-\uFFFF][$\w\xA0-\uFFFF]*(?=\.(?:prototype|constructor))/g

const matches = match_me.match(regex)

console.log(matches)