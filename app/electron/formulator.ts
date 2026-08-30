import type { BrowserWindow } from 'electron';

import { type Binding, type FoundryEnv, runFoundryJson, runFoundry } from './foundry.js';
import { Pane } from './harness/pane.js';

/**
 * Data Formulator, as a leased reader on one locked window (KTD3).
 *
 * The app owns almost none of this. `launch-formulator` claims the window's
 * lease, spawns the process, waits for it to answer and confirms the served
 * process is this window's; `stop-formulator` refuses to kill a process whose
 * identity it cannot prove. All of that lives in the kit because a re-import has
 * to be able to take the lease back, and only the library knows when that
 * happens. What is left here is a URL, a rectangle, and stopping on the way out.
 *
 * It is a reader, not a peer engine: Formulator copies rows into its own
 * workspace after a read-only fetch, and a figure read off one of its charts is
 * 稿外追问 rather than something the brief said.
 */

/** What `launch-formulator` prints. `identity` is present only when it is unsure. */
export interface LaunchSpec {
  url: string;
  home: string;
  identity?: string;
}

export class FormulatorHost {
  private readonly pane = new Pane();
  private spec: LaunchSpec | null = null;

  running(): LaunchSpec | null {
    return this.spec;
  }

  /**
   * Start it for the current window and put its page in the window.
   *
   * Every refusal the kit can give comes back as itself: a window that is not
   * locked, a port already busy, a second launch on the same window, or the
   * binary not being installed. None of those is this app's sentence to write.
   */
  async launch(binding: Binding, window: BrowserWindow, env?: FoundryEnv): Promise<LaunchSpec> {
    const spec = await runFoundryJson<LaunchSpec>(binding, 'launch-formulator', [], env);
    this.spec = spec;
    await this.pane.attach(window, spec.url);
    return spec;
  }

  /**
   * Stop it, and forget it even if the stop refused.
   *
   * A refusal here means the kit would not kill a process it could not confirm.
   * The page still has to go: leaving a view pointed at a server this app no
   * longer claims is worse than showing nothing.
   */
  async stop(binding: Binding, window: BrowserWindow, env?: FoundryEnv): Promise<void> {
    try {
      await runFoundry(binding, 'stop-formulator', [], env);
    } finally {
      this.spec = null;
      this.pane.detach(window);
    }
  }

  place(window: BrowserWindow, visible: boolean): void {
    this.pane.place(window, visible);
  }
}
