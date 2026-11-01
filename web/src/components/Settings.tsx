import { useEffect, useState } from "react";
import { ArrowClockwiseIcon, FolderOpenIcon, ScissorsIcon, WaveformIcon, YoutubeLogoIcon } from "@phosphor-icons/react";
import { api, errorText } from "../lib/api";
import { FORMAT_HELP, FORMAT_LABELS, QUALITY_HELP, QUALITY_LABELS, SOURCE_INFO, when } from "../lib/format";
import { update, useStore } from "../lib/store";
import type { OutputFormat, Quality, Settings as SettingsShape, Source } from "../lib/types";
import { Button } from "./ui/Button";
import { Field } from "./ui/Field";
import { Notice } from "./ui/Notice";
import { Segmented } from "./ui/Segmented";
import { Switch } from "./ui/Switch";

const SOURCES: Source[] = ["soulseek", "youtube", "mix"];
const SOURCE_ICONS = { soulseek: WaveformIcon, youtube: YoutubeLogoIcon, mix: ScissorsIcon } as const;

/** Where tracks come from, quality and files, the Soulseek login, yt-dlp and the folders. */
export function Settings() {
  const state = useStore((d) => d.state);
  const [musicDir, setMusicDir] = useState("");
  const [sockseek, setSockseek] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [prefError, setPrefError] = useState<string | null>(null);
  const [ytError, setYtError] = useState<string | null>(null);

  useEffect(() => {
    if (!state) return;
    setMusicDir(state.settings.music_dir);
    setSockseek(state.settings.sockseek);
  }, [state?.settings.music_dir, state?.settings.sockseek]);

  if (!state) return null;
  const login = state.login;
  const s = state.settings;
  const yt = state.ytdlp;

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

  // Sources, quality and files save as soon as they change
  async function savePref(changes: Partial<SettingsShape>) {
    setPrefError(null);
    update((d) => (d.state ? { state: { ...d.state, settings: { ...d.state.settings, ...changes } } } : {}));
    try {
      update({ state: await api.saveSettings(changes) });
    } catch (e) {
      setPrefError(errorText(e));
      try {
        update({ state: await api.state() });
      } catch {
        // shown as it was
      }
    }
  }

  function toggleSource(src: Source, on: boolean) {
    const next = on ? SOURCES.filter((x) => x === src || s.sources.includes(x)) : s.sources.filter((x) => x !== src);
    void savePref({ sources: next });
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

  async function ytdlp(act: () => Promise<{ ytdlp: typeof yt }>) {
    setYtError(null);
    try {
      const res = await act();
      update((d) => (d.state ? { state: { ...d.state, ytdlp: res.ytdlp } } : {}));
    } catch (e) {
      setYtError(errorText(e));
    }
  }

  const noSource = s.sources.length === 0;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8 px-8 py-10">
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>

      <section className="flex flex-col gap-3" aria-labelledby="sources-h">
        <div>
          <h2 id="sources-h" className="text-sm font-semibold">
            Where tracks come from
          </h2>
          <p className="mt-0.5 text-xs text-fg-3">Tried in this order. What one doesn't find goes to the next.</p>
        </div>
        <ol className="flex flex-col overflow-hidden rounded-panel border border-line">
          {SOURCES.map((src, i) => {
            const Icon = SOURCE_ICONS[src];
            const on = s.sources.includes(src);
            const id = `source-${src}`;
            return (
              <li key={src} className={`flex items-start gap-3 px-3.5 py-3 ${i ? "border-t border-line" : ""}`}>
                <span className="mt-0.5 w-4 shrink-0 text-right font-mono text-xs tabular text-fg-3">{i + 1}</span>
                <Icon size={17} className={`mt-px shrink-0 ${on ? "text-fg-2" : "text-fg-3"}`} aria-hidden />
                <div className="min-w-0 flex-1">
                  <label htmlFor={id} className={`text-sm font-medium ${on ? "text-fg" : "text-fg-2"}`}>
                    {SOURCE_INFO[src].name}
                  </label>
                  <p className="mt-0.5 text-xs text-fg-3">{SOURCE_INFO[src].help}</p>
                </div>
                <Switch id={id} label={SOURCE_INFO[src].name} checked={on} onChange={(v) => toggleSource(src, v)} />
              </li>
            );
          })}
        </ol>
        {noSource && (
          <Notice tone="warn">Every source is off, so nothing can be downloaded. Turn one on.</Notice>
        )}
      </section>

      <section className="flex flex-col gap-3 border-t border-line pt-6" aria-labelledby="login-h">
        <h2 id="login-h" className="text-sm font-semibold">
          Soulseek login
        </h2>
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
          {login.source === "none" &&
            (s.sources.includes("soulseek")
              ? "No login yet. Downloads and searches on Soulseek need an account."
              : "No login yet. Soulseek is off, so none is needed.")}
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

      <section className="flex flex-col gap-4 border-t border-line pt-6" aria-labelledby="quality-h">
        <h2 id="quality-h" className="text-sm font-semibold">
          Quality and files
        </h2>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-2">Soulseek quality</span>
          <div>
            <Segmented<Quality>
              label="Soulseek quality"
              value={s.quality}
              onChange={(q) => void savePref({ quality: q })}
              options={(["lossless", "best", "fast"] as Quality[]).map((q) => ({ value: q, label: QUALITY_LABELS[q] }))}
            />
          </div>
          <p className="text-xs text-fg-3">{QUALITY_HELP[s.quality]}</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-2">Output format</span>
          <div>
            <Segmented<OutputFormat>
              label="Output format"
              value={s.format}
              onChange={(f) => void savePref({ format: f })}
              options={(["keep", "flac", "aiff", "mp3", "wav"] as OutputFormat[]).map((f) => ({ value: f, label: FORMAT_LABELS[f] }))}
            />
          </div>
          <p className="text-xs text-fg-3">{FORMAT_HELP[s.format]}</p>
        </div>
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <label htmlFor="tags" className="text-sm font-medium text-fg">
              Write tags and covers
            </label>
            <p className="mt-0.5 text-xs text-fg-3">
              Artist and title from the tracklist, the set as the album, its position as the track number, where the file came
              from, and a cover when the file has none.
            </p>
          </div>
          <Switch id="tags" label="Write tags and covers" checked={s.tags} onChange={(v) => void savePref({ tags: v })} />
        </div>
        <p className="text-xs text-fg-3">
          Applied after each download. A set downloaded before is converted with Finish files on the set.
        </p>
        {prefError && <Notice tone="bad">{prefError}</Notice>}
      </section>

      <section className="flex flex-col gap-3 border-t border-line pt-6" aria-labelledby="ytdlp-h">
        <h2 id="ytdlp-h" className="text-sm font-semibold">
          yt-dlp
        </h2>
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1 text-sm text-fg-2">
            {yt.version ? (
              <>
                <span className="font-mono text-xs tabular text-fg">{yt.version}</span>
                {yt.source === "updated" ? (
                  <>
                    {" "}
                    updated {when(yt.updated).replace(/^(Today|Yesterday)/, (m) => m.toLowerCase())}. The built-in{" "}
                    {yt.bundled ?? "copy"} stays as the fallback.
                  </>
                ) : (
                  <> built in.</>
                )}
              </>
            ) : yt.source === "bundled" ? (
              "Checking the version..."
            ) : (
              "yt-dlp isn't installed, so YouTube can't be used."
            )}
            <p className="mt-0.5 text-xs text-fg-3">
              Reads YouTube, SoundCloud and Mixcloud. When they change, an older copy stops working: update it then.
            </p>
          </div>
          {yt.source === "updated" && !yt.updating && (
            <Button variant="ghost" size="sm" onClick={() => void ytdlp(api.revertYtdlp)}>
              Use the built-in one
            </Button>
          )}
          <Button
            icon={<ArrowClockwiseIcon size={15} aria-hidden className={yt.updating ? "animate-spin motion-reduce:animate-none" : ""} />}
            onClick={() => void ytdlp(api.updateYtdlp)}
            disabled={yt.updating}
          >
            {yt.updating ? "Updating" : "Update yt-dlp"}
          </Button>
        </div>
        {yt.updating && (
          <div className="anim-fade flex flex-col gap-1.5">
            <div className="progress" aria-hidden />
            <p role="status" className="text-xs text-fg-2">
              {yt.step}...
            </p>
          </div>
        )}
        {!yt.updating && yt.message && !yt.error && (
          <p role="status" className="anim-fade text-xs text-ok">
            {yt.message}
          </p>
        )}
        {!yt.updating && (yt.error || ytError) && <Notice tone="bad">{yt.error || ytError}</Notice>}
        <p className="text-xs text-fg-3">Updates come from yt-dlp's releases on GitHub and are checked before they're used.</p>
      </section>

      <section className="flex flex-col gap-3 border-t border-line pt-6" aria-labelledby="folders-h">
        <h2 id="folders-h" className="text-sm font-semibold">
          Folders
        </h2>
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
          help={state.sockseek.found ? `Using ${state.sockseek.path}` : (state.sockseek.error ?? "sockseek wasn't found.")}
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
