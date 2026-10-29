import { cp, mkdir, readdir, rm, stat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const frontendDirectory = path.resolve(scriptDirectory, '..')
const projectRoot = path.resolve(frontendDirectory, '..')
const buildDirectory = path.join(frontendDirectory, 'dist')
const publicDirectory = path.join(projectRoot, 'public')

async function main() {
  const indexPath = path.join(buildDirectory, 'index.html')
  try {
    if (!(await stat(indexPath)).isFile()) {
      throw new Error('not a file')
    }
  } catch {
    console.error(`Frontend build entrypoint is missing: ${indexPath}`)
    process.exitCode = 1
    return
  }

  await rm(publicDirectory, { recursive: true, force: true })
  await mkdir(publicDirectory, { recursive: true })

  for (const entry of await readdir(buildDirectory)) {
    await cp(
      path.join(buildDirectory, entry),
      path.join(publicDirectory, entry),
      { recursive: true },
    )
  }

  console.log(`Copied frontend build into ${publicDirectory}`)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
