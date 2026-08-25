
const regex_ = /(?:x(?:...|(...))\1x)+/;
const strr = 'xcbccbcxxcbbcbbxxabacbbxxbcbbcbxxabacbbxxcbccbcx';

const match = regex_.exec(strr);
const is_match = regex_.test(strr);
const strict_match = strr.match(regex_);

console.log('Match:');
console.log(match);
console.log('Is match:');
console.log(is_match);
console.log('Strict match:');
console.log(strict_match);

const regex_1 = /(?:x(?:...|(...))\1x)/;
const strr_1 = '21kj3hedkjhakhwkhjekxabcabcx32o1jkdflsjdkal';

const match_1 = regex_1.exec(strr_1);
const is_match_1 = regex_1.test(strr_1);
const strict_match_1 = strr_1.match(regex_1);

console.log('Match 1:');
console.log(match_1);
console.log('Is match 1:');
console.log(is_match_1);
console.log('Strict match 1:');
console.log(strict_match_1);

const strr_2 = 'xabaabaxxcaccacxxacccacxxccccacx';

const match_2 = regex_.exec(strr_2);
const is_match_2 = regex_.test(strr_2);
const strict_match_2 = strr_2.match(regex_);

console.log('Match 2:');
console.log(match_2);
console.log('Is match 2:');
console.log(is_match_2);
console.log('Strict match 2:');
console.log(strict_match_2);