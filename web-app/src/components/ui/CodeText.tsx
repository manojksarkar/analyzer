/** Text whose backticked parts (paths, config keys, commands) show as code — how the API, the
 *  engine and the config import's report write them. Never HTML: each part is a text node. An
 *  unpaired backtick opens nothing; it stays as written. */
export function CodeText({ text }: { text: string }) {
  const parts = text.split('`')
  if (parts.length % 2 === 0) {
    const tail = parts.splice(-2, 2)
    parts.push(tail.join('`'))
  }
  return (
    <>
      {parts.map((part, i) =>
        i % 2
          ? <code key={i} className="font-mono text-caption bg-surface-container-low px-1 rounded">{part}</code>
          : part)}
    </>
  )
}
