"""Official CCDC web access with a private persistent account session."""
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject,Qt,QUrl
from PySide6.QtWidgets import QFileDialog,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QVBoxLayout

from xrd_finder.services.cache_paths import default_data_root
from xrd_finder.services.ccdc_lookup import CCDC_HOME,CCDC_LOGIN,ccdc_query,ccdc_search_url,find_cached_ccdc,import_ccdc_download
from xrd_finder.services.network import ensure_online_allowed,offline_mode_enabled
from xrd_finder.ui.screen_bound_dialog import ScreenBoundDialog


def _display_url(url):
    display = QUrl(url)
    display.setUserInfo('')
    return display.toDisplayString()


def ccdc_profile_directory():
    # Account cookies must never be part of a shared prepared phase library.
    return default_data_root()/'ccdc_web_session'


class _CcdcDialog(ScreenBoundDialog):
    def __init__(self,controller):
        super().__init__(controller.owner)
        from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineUrlRequestInterceptor
        from PySide6.QtWebEngineWidgets import QWebEngineView

        class NetworkPolicy(QWebEngineUrlRequestInterceptor):
            def interceptRequest(self,info):
                if offline_mode_enabled() and info.requestUrl().scheme() in ('http','https'):
                    info.block(True)

        self.controller = controller
        self.setWindowTitle('CCDC Access Structures')
        self.resize(1100,800)
        layout = QVBoxLayout(self)
        navigation = QHBoxLayout()
        self.query = QLineEdit();self.query.setPlaceholderText('CCDC number / CSD refcode / DOI')
        search = QPushButton('Search');account = QPushButton('Sign in / account')
        local = QPushButton('Import downloaded CIF…')
        navigation.addWidget(self.query,1);navigation.addWidget(search);navigation.addWidget(account);navigation.addWidget(local)
        layout.addLayout(navigation)
        self.address = QLabel();self.address.setWordWrap(True)
        self.address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.address)
        self.status = QLabel('Simple Search uses the published collection. Sign-in is optional. Your CCDC session stays on this computer; Finder does not store your password in its settings.')
        self.status.setWordWrap(True);layout.addWidget(self.status)
        # Delete the view/pages before their profile when the dialog is destroyed.
        self.view = QWebEngineView(self);layout.addWidget(self.view,1)
        self.profile = QWebEngineProfile('Finder-CCDC',self)
        folder = ccdc_profile_directory();folder.mkdir(parents=True,exist_ok=True)
        self.profile.setPersistentStoragePath(str(folder/'storage'))
        self.profile.setCachePath(str(folder/'cache'))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.policy = NetworkPolicy(self.profile);self.profile.setUrlRequestInterceptor(self.policy)
        page = QWebEnginePage(self.profile,self.view);self.view.setPage(page)
        self.view.urlChanged.connect(lambda url:self.address.setText(_display_url(url)))
        self.view.loadFinished.connect(lambda ok:self.status.setText(
            'Choose the required structure and its CIF download on CCDC. Downloaded CIFs are added to Finder candidates.' if ok else
            'CCDC page could not be loaded. Check network access or use Import downloaded CIF.'))
        # Keep first-party sign-in links and user-requested new windows in this
        # same visible profile. Credentials stay inside the official web page.
        page.newWindowRequested.connect(lambda request:self.view.setUrl(request.requestedUrl()))
        self.profile.downloadRequested.connect(controller.download_requested)
        search.clicked.connect(lambda:controller.open(self.query.text()))
        self.query.returnPressed.connect(lambda:controller.open(self.query.text()))
        account.clicked.connect(lambda:controller.open(login=True))
        local.clicked.connect(controller.choose_downloaded_cif)

    def closeEvent(self,event):
        self.view.stop()
        for download in tuple(self.controller.downloads):
            if not download.isFinished():download.cancel()
        event.accept()


class CcdcPortalController(QObject):
    def __init__(self,owner):
        super().__init__(owner)
        self.owner = owner
        self.dialog = None
        self.query = ''
        self.downloads = set()

    def open(self,query='',*,login=False):
        if query:
            self.query = ccdc_query(query)[1]
            cached = find_cached_ccdc(self.owner.local_phase_cache,self.query)
            if cached:
                self.present(cached)
                self.owner._set_background_status(f'CCDC: {len(cached)} saved structure(s)')
                return
        ensure_online_allowed('CCDC Access Structures')
        if self.dialog is None:
            self.dialog = _CcdcDialog(self)
        if query:self.dialog.query.setText(self.query)
        url = CCDC_LOGIN if login else (ccdc_search_url(query) if query else CCDC_HOME)
        self.dialog.view.setUrl(QUrl(url))
        self.dialog.show();self.dialog.raise_();self.dialog.activateWindow()

    def shutdown(self):
        if self.dialog is not None:self.dialog.close()

    def present(self,entries):
        if getattr(self.owner,'_preparation_close_confirmed',False):return
        self.owner._set_search_mode('search')
        rows = self.owner.candidate_search_service.cache_rows(entries)
        self.owner._record_initial_candidate_rows(rows)
        self.owner._set_candidate_rows(rows)
        self.owner._refresh_database_rows()

    def download_requested(self,download):
        page = download.page()
        host = page.url().host().lower() if page is not None else ''
        if host!='ccdc.cam.ac.uk' and not host.endswith('.ccdc.cam.ac.uk'):
            download.cancel();return
        name = download.downloadFileName()
        suffix = Path(name).suffix.lower()
        if suffix not in {'.cif','.zip'}:
            download.cancel()
            self.dialog.status.setText('Choose the CIF/structure download, or import a downloaded CIF file.')
            return
        root = default_data_root()/'ccdc_downloads';root.mkdir(parents=True,exist_ok=True)
        filename = uuid4().hex+suffix
        download.setDownloadDirectory(str(root));download.setDownloadFileName(filename)
        query,token = self.query,getattr(self.owner,'_candidate_search_request_token',0)
        self.downloads.add(download)
        def finished():
            if not download.isFinished():return
            self.downloads.discard(download)
            from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
            if download.state()==QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
                self.import_file(root/filename,query,token)
            elif self.dialog is not None:
                self.dialog.status.setText('CCDC download stopped: '+download.interruptReasonString())
        download.isFinishedChanged.connect(finished)
        self.dialog.status.setText('Downloading CIF from CCDC…')
        # This accepts a file download explicitly initiated by the user on the
        # official site. It never accepts site terms, signs in, or submits a form.
        download.accept()

    def choose_downloaded_cif(self):
        path,_ = QFileDialog.getOpenFileName(self.owner,'Import downloaded CCDC structure',str(Path.home()/'Downloads'),'CCDC data (*.cif *.zip)')
        if path:self.import_file(Path(path),self.query,getattr(self.owner,'_candidate_search_request_token',0))

    def import_file(self,path,query,token):
        if getattr(self.owner,'_preparation_close_confirmed',False):return
        def done(result):
            if token==getattr(self.owner,'_candidate_search_request_token',0) and result.entries:
                self.present(result.entries)
            text=f'CCDC: {len(result.entries)} structure(s) prepared'
            if result.errors:
                text+='; '+str(len(result.errors))+' could not be prepared.'
                text+='\n'+'\n'.join(list(result.errors.values())[:3])
            self.owner._set_background_status(text)
            if self.dialog is not None:self.dialog.status.setText(text)
            if result.entries and self.dialog is not None:self.dialog.hide()
        self.owner._run_background_task('CCDC structure','Preparing downloaded CCDC structures…',
            lambda progress:import_ccdc_download(self.owner.local_phase_cache,path,query,progress=progress,
                cancelled=lambda:getattr(self.owner,'_preparation_close_confirmed',False)),
            done,with_progress=True,show_progress_dialog=True,operation_name='ccdc.import')
