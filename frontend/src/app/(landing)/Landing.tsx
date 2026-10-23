import { buttonVariants } from "@/components/ui/button";
import { copy } from "@/i18n";
import type { SignInOptions } from "@/lib/api";
import { REPOSITORY_URL } from "@/lib/repository";
import { PROVIDER_LABELS } from "@/lib/signIn";

import { LandingEntry } from "./LandingEntry";

const t = copy.landing;
const p = t.prototype;

/** 单角色本地入口。姓名排版是无形象资源时的占位，不请求旧作品的媒体或演示数据。 */
export function Landing({ isSignedIn, signInOptions }: { isSignedIn: boolean; signInOptions: SignInOptions | null }) {
  const entryLabel = isSignedIn ? t.continue : t.signIn;
  const providers = signInOptions?.providers.map((provider) => PROVIDER_LABELS[provider]) ?? [];
  return (
    <div className="lp-root gim-landing">
      <a className="gim-skip" href="#gim-main">{p.skip}</a>
      <header className="gim-header">
        <a href="/" className="gim-wordmark">{copy.app.name}</a>
        <div className="flex items-center gap-3">
          <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer" className={buttonVariants({ variant: "ghost" })}>
            {copy.app.repositoryLabel}
          </a>
          <LandingEntry isSignedIn={isSignedIn} label={entryLabel} className={buttonVariants({ variant: "outline" })} />
        </div>
      </header>

      <main id="gim-main" tabIndex={-1}>
        <section className="gim-hero" aria-labelledby="lp-title">
          <div className="lp-beam" aria-hidden />
          <div className="gim-hero-copy">
            <h1 id="lp-title">{p.title}</h1>
            <p className="gim-lede">{copy.app.description}</p>
            <p className="gim-body">{p.intro}</p>
            <div className="gim-actions">
              <LandingEntry isSignedIn={isSignedIn} label={isSignedIn ? p.resume : p.start} className={buttonVariants({ size: "call" })} />
              <a href="#gim-scope">{p.scopeLink}</a>
            </div>
            <p className="gim-note">{t.disclaimer}</p>
          </div>
          <figure className="gim-nameplate">
            <p lang="ja">{p.name}</p>
            <figcaption>{p.placeholder}</figcaption>
          </figure>
        </section>

        <section id="gim-scope" className="gim-scope" aria-labelledby="gim-scope-title">
          <div>
            <h2 id="gim-scope-title">{p.scopeTitle}</h2>
            <p className="gim-body">{p.scopeBody}</p>
          </div>
          <dl className="gim-facts">
            {p.facts.map((fact) => (
              <div key={fact.title}>
                <dt>{fact.title}</dt>
                <dd>{fact.body}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="gim-start" aria-labelledby="gim-start-title">
          <h2 id="gim-start-title">{p.startTitle}</h2>
          <p className="gim-body">{p.data}</p>
          {signInOptions && (
            <p className="gim-note">
              {providers.length > 0 ? p.providers(providers.join("、")) : signInOptions.dev_login ? p.devLogin : p.noLogin}
            </p>
          )}
          <LandingEntry isSignedIn={isSignedIn} label={isSignedIn ? p.resume : p.start} className={buttonVariants({ size: "call" })} />
        </section>
      </main>

      <footer className="gim-footer">
        <p>{copy.legal.disclaimer}</p>
        <nav aria-label={p.footerLabel}>
          <a href="/privacy">{copy.legal.privacy}</a>
          <a href="/terms">{copy.legal.terms}</a>
          <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer">{copy.app.repositoryLabel}</a>
        </nav>
      </footer>
    </div>
  );
}
