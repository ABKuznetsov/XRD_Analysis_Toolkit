# First-run showcase and environment setup design

## Purpose

Replace the visible command-line environment installer with a clear first-run experience. The application must explain what is missing, ask the user before installing, show real installation progress, and use the wait time to demonstrate important XRD Phase Finder capabilities with real screenshots.

## Audience and launch rules

### New user or incomplete runtime

- The startup runtime probe checks the Python executable and imports all required packages.
- If Python, `pythonw.exe`, or packages are missing or damaged, the window lists the exact failed checks.
- Nothing is installed until the user presses **«Обновить или доустановить»**.
- After confirmation, the command prompt remains hidden and the showcase stays visible for the entire installation.
- The installation showcase cannot be skipped or closed while installation is active.
- Previous and next arrows remain available and the cards also advance automatically.
- Closing Windows or cancelling the process is not offered as an ordinary UI action during installation.

### Existing user with a ready runtime

- The showcase appears once on the first launch of XRD Phase Finder 1.4.0.
- It can be skipped, navigated with arrows, or allowed to advance automatically.
- Completion or skipping writes a versioned marker under `%LocalAppData%\Sci\XRD_Finder`.
- Later 1.4.0 launches do not show it again.
- A later release can show a new showcase by changing the marker version.

## Window composition

The existing startup window remains the host and is expanded into two areas:

- Left: application identity and live environment progress.
- Right: showcase image, action title, one concise benefit statement, navigation arrows, position indicators, and contextual action buttons.

The progress area always names the current operation, for example Python installation, package download, package installation, runtime verification, or application launch. When package progress can be parsed, it displays the package name and `N of M`; otherwise it shows an indeterminate progress indicator without inventing a percentage.

## Showcase cards

Cards use action verbs rather than internal subsystem names.

1. **Выбрать** — select elements and candidate sources. Uses the Elements and Databases screenshots.
2. **Обработать** — smooth the pattern and separate physical or amorphous background. Uses the smoothing/background dialogs and `amor.png`.
3. **Найти** — identify the first phase by Match and additional phases by Gain. Uses a complete fitted multiphase pattern from the article.
4. **Проверить** — inspect phase classification, unit-cell parameters, atomic positions, and original source. Uses the Card screenshot.
5. **Сравнить** — display multiple patterns and series together with phase markers. Uses `multi.jpg` and its component figures from the article.
6. **Настроить** — control axes, scale, grid, labels, markers, legend, and publication aspect ratio. Uses the View screenshot.
7. **Экспортировать и передать** — export a publication-quality figure and save a portable `.xpff` containing patterns, user CIFs, phases, and processing state. Uses a publication figure and project-tree crop.

Each image is copied into a dedicated installer asset directory in the repository, cropped for the showcase without destructive changes to the article originals, and scaled with preserved aspect ratio.

## Performance notice

One of the first cards contains a calm warning:

> Поиск по большим базам, построение многих профилей и обработка крупных серий могут занять время на слабом компьютере. Не закрывайте программу: текущая операция отображается в окне и строке состояния.

The message must not imply that hanging is normal. It explains which workloads can be slow and where the user can see progress.

## Installation completion

- If installation finishes before the user reaches the last card, the user may keep browsing or press **«Запустить XRD Phase Finder»**.
- If the cards finish first, they continue cycling until installation completes.
- Runtime readiness is verified again by executing the probe and importing requirements.
- The application is launched only after this verification succeeds.

## Failure behavior

- The same window displays the exact failed component or setup error.
- Buttons are **«Повторить»**, **«Открыть журнал»**, and **«Закрыть»**.
- **«Повторить»** performs the same full repair and verification again.
- **«Открыть журнал»** opens `%LocalAppData%\Sci\logs\setup.log` without closing the window.
- Closing after failure is permitted because no setup process is running.
- The installer does not separately launch `setup_sci_env.bat`; all runtime setup is coordinated by the startup UI.

## Component boundaries

- `toolkit/first_run_showcase.ps1`: showcase card definitions, navigation, marker persistence, and image loading.
- `toolkit/sci_runtime_setup_ui.ps1`: runtime diagnosis text, user confirmation, setup-process monitoring, retry, and log access.
- `toolkit/launch_xrd_finder_preview.ps1`: startup orchestration only; dot-sources the two focused modules and launches the application after readiness.
- `toolkit/showcase/`: packaged PNG/JPEG assets and a small manifest containing card order, action labels, and descriptions.

The scientific application remains independent of this UI; no Phase Finder analysis logic changes.

## Acceptance criteria

- A clean computer receives a clear list of missing components and no installation begins without confirmation.
- No command-line window appears during setup.
- Setup progress and the currently handled component remain visible.
- The installation showcase cannot be skipped; the ready-runtime showcase can be skipped on its one-time 1.4.0 appearance.
- Navigation arrows and automatic rotation both work.
- The slowdown notice is visible in the showcase.
- Successful repair is followed by a real runtime self-test and application launch.
- Failed repair gives the reason, retry, log access, and close actions.
- Existing launches after the first ready-runtime showcase are not delayed by it.
