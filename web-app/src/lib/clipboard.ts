/** Copy text to the clipboard. `navigator.clipboard` exists only in a secure context (https, or
 *  localhost): the office opens the app over plain http by the server's address, where it is
 *  undefined and a copy button did nothing. There a hidden textarea and `execCommand('copy')` do it.
 *  True when the text was copied. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to the textarea
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.className = 'fixed -left-[9999px] top-0 opacity-0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}
