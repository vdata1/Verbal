const match_me = "덼檂ᅁﲕ鮞ࡦ乐\udebe暹侗춊ᙄ䁤ᔊ듂䝇綾ꓦ" // This string is so odd lol. Unquote it and see.
const regex = /[_$A-Z\xA0-\uFFFF][$\w\xA0-\uFFFF]*(?=\.(?:prototype|constructor))/g

const matches = match_me.match(regex)

console.log(matches)