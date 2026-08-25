#regex: Watch plugins OffendingFooThirdPartyWatchPlugin and OffendingBarThirdPartyWatchPlugin both attempted to register key <!>\.\s+Please change the key configuration for one of the conflicting plugins to avoid overlap\. 
<start> ::= "Watch plugins OffendingFooThirdPartyWatchPlugin and OffendingBarThirdPartyWatchPlugin both attempted to register key <!>." (<r0>)? "Please change the key configuration for one of the conflicting plugins to avoid overlap."
<r0> ::= r'[ \t\n\r\f\v]'
