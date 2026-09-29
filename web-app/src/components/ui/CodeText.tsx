/** Text whose backticked parts (paths, config keys) show as code — how the config import's
 *  report and the path check write them. */
export function CodeText({ text }: { text: string }) {
  return (
    <>
      {text.split('`').map((part, i) =>
        i % 2
          ? <code key={i} className="font-mono text-caption bg-surface-container-low px-1 rounded">{part}</code>
          : part)}
    </>
  )
}
