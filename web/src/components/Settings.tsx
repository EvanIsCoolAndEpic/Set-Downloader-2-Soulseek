import { useEffect, useState } from "react";
import { FolderOpenIcon } from "@phosphor-icons/react";
import { api, errorText } from "../lib/api";
import { update, useStore } from "../lib/store";
import { Button } from "./ui/Button";
import { Field } from "./ui/Field";
import { Notice } from "./ui/Notice";

/** Where sets go, the Soulseek login and the sockseek program. */
export function Settings() {
  const state = useStore((d) => d.state);
  const [musicDir, setMusicDir] = useState("");
  const [sockseek, setSockseek] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!state) return;
    setMusicDir(state.settings.music_dir);
    setSockseek(state.settings.sockseek);
  }, [state?.settings.music_dir, state?.settings.sockseek]);

  if (!state) return null;
  const login = state.login;

  async function run(what: string, act: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      await act();
      setSaved(what);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const saveFolders = () =>
    run("Saved.", async () => {
      const next = await api.saveSettings({ music_dir: musicDir.trim(), sockseek: sockseek.trim() });
      update({ state: next });
    });

  const saveLogin = () =>
    run("Login saved.", async () => {
      const res = await api.saveLogin(username.trim(), password);
      setPassword("");
      update((d) => ({ state: d.state ? { ...d.state, login: res.login } : d.state }));
    });

  const forgetLogin = () =>
    run("Login removed.", async () => {
      const res = await api.forgetLogin();
      update((d) => ({ state: d.state ? { ...d.state, login: res.login } : d.state }));
    });

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8 px-8 py-10">
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Soulseek login</h2>
        <p className="text-sm text-fg-2">
          {login.source === "app" && (
            <>
              Signed in as <span className="font-medium text-fg">{login.username}</span>.
            </>
          )}
          {login.source === "mixxx" && (
            <>
              Using the login saved by the Mixxx fork
              {login.username ? (
                <>
                  {" "}
                  (<span className="font-medium text-fg">{login.username}</span>)
                </>
              ) : null}
              . Save one here to use your own.
            </>
          )}
          {login.source === "none" && "No login yet. Downloads and searches need a Soulseek account."}
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <Field
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => void saveLogin()} disabled={busy || !username.trim() || !password}>
            Save login
          </Button>
          {login.source === "app" && (
            <Button variant="ghost" onClick={() => void forgetLogin()} disabled={busy}>
              Remove
            </Button>
          )}
        </div>
        <p className="text-xs text-fg-3">Kept on this Mac only, readable by you alone.</p>
      </section>

      <section className="flex flex-col gap-3 border-t border-line pt-6">
        <h2 className="text-sm font-semibold">Folders</h2>
        <div className="flex items-end gap-2">
          <Field
            className="flex-1"
            label="Music folder"
            mono
            value={musicDir}
            onChange={(e) => setMusicDir(e.target.value)}
            help={state.music_dir.exists ? "Each set gets a folder in here." : "This folder doesn't exist yet. It's made with the first set."}
          />
          <Button
            icon={<FolderOpenIcon size={15} aria-hidden />}
            onClick={() => void api.reveal({ path: state.music_dir.path }).catch((e) => setError(errorText(e)))}
            className="mb-[22px]"
            disabled={!state.music_dir.exists}
          >
            Show
          </Button>
        </div>
        <Field
          label="sockseek program"
          mono
          placeholder="Found automatically"
          value={sockseek}
          onChange={(e) => setSockseek(e.target.value)}
          help={
            state.sockseek.found
              ? `Using ${state.sockseek.path}`
              : (state.sockseek.error ?? "sockseek wasn't found.")
          }
        />
        <div>
          <Button onClick={() => void saveFolders()} disabled={busy}>
            Save folders
          </Button>
        </div>
      </section>

      {error && <Notice tone="bad">{error}</Notice>}
      {saved && !error && <p className="text-sm text-ok">{saved}</p>}
    </div>
  );
}
