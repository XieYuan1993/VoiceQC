export function knowledgeTriggerRanges(text: string, terms: string[]): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  for (const term of new Set(terms)) {
    const characters = Array.from(term.trim());
    if (!characters.length) continue;
    const pattern = characters.filter((character) => !/\s/u.test(character))
      .map((character) => character.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("[\\s,，]*");
    if (!pattern) continue;
    const expression = new RegExp(pattern, "giu");
    for (const match of text.matchAll(expression)) {
      const start = match.index;
      const end = start + match[0].length;
      if (/^[\x00-\x7F]+$/.test(term) && (/[a-z0-9]/i.test(text[start - 1] ?? "") || /[a-z0-9]/i.test(text[end] ?? ""))) continue;
      ranges.push([start, end]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  const merged: Array<[number, number]> = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range[0] < last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}
