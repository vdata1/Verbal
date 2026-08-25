STR_TO_MATCH = "à½²è©½àª¸?ã?ã·µì­ë¯ì«é¹áä·ä·î¸¨?ë¤â¿«é ê¨¥å¶èá±ïë´èµç£ã¦ä«ã¨¾æ®à±¡è¼«î£îªçºï§î³¸é»æ¯»ê°æ°®á´¦î·ëë¤á¹¸é³½çî¼é§Â¡âà©âë´ëÙí¶è¾éì±ì®á áè³ã±çºîáí æ¼ä°®æ¦¹ãµã©¡ä³´ë¹ê?ï±µëå£?ë­ºã¢ê¦°î¸¥ëé¨èí?à"
REGEX = r'[_$A-Z\xA0-\uFFFF][$\w\xA0-\uFFFF]*(?=\.(?:prototype|constructor))'

if __name__ == "__main__":
    import re
    matches = re.findall(REGEX, STR_TO_MATCH)
    print(matches)

    str_encoded = STR_TO_MATCH.encode('utf-8')
    print(str_encoded)