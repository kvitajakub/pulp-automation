import requests, json, contextlib, gevent, logging
from requests.adapters import HTTPAdapter
from . import (normalize_url, path_join, path as pulp_path, static_path as pulp_static_path)
from handler import logged
from M2Crypto import (RSA, BIO)
from requests.structures import CaseInsensitiveDict as cidict
log = logging.getLogger(__name__)


class Pulp(object):
    
    '''
    # Response codes
    
    OK = "200"
    CREATED = "201"
    ACCEPTED = "202"

    BAD_REQUEST = "400"
    UNAUTHORIZED = "401"
    NOT_FOUND = "404"
    CONFLICT = "409"

    INTERNAL_SERVER_ERROR = "500"
    NOT_IMPLEMENTED = "501"
    SERVICE_UNAVAILABLE = "503"
    '''
    
    '''Pulp handle'''
    check_function = staticmethod(lambda x: x.status_code >= 200 and x.status_code < 400)

    def __init__(self, url, auth=None, verify=False, asserting=False, adapter=HTTPAdapter(max_retries=3)):
        self.url = url
        self.session = requests.Session()
        # a transport adapter is mounted to the session
        self.session.mount(url, adapter)
        self.auth = auth
        self.verify = verify
        self.last_response = None
        self.last_request = None
        self._asserting = asserting
        self._async = False
        self._pubkey = None

        try:
            from gevent.coros import BoundedSemaphore
        except ImportError:
            from gevent.lock import BoundedSemaphore

        self._semaphore = BoundedSemaphore(1)

    @classmethod
    def copy(cls, other, adapter=HTTPAdapter(max_retries=3), asserting=False):
        '''copy constructor; does not copy internal state'''
        return cls(other.url, auth=other.auth, verify=other.verify, adapter=adapter, asserting=asserting)

    @logged(log.debug)
    def send(self, request):
        '''send a request; the request has to be callable that accepts url and auth params; locking'''
        if self._async:
            # when in async mode, just "queue" requests
            self.last_request += (request(self.url, self.auth), )
            return
        with self._semaphore:
            self.last_request = request(self.url, self.auth)
            last_response = self.session.send(self.last_request, verify=self.verify)
            self.last_response = last_response
            if self._asserting:
                assert self.is_ok, 'pulp was not OK:\n' + \
                    format_preprequest(self.last_request) + format_response(self.last_response)
                pass
        return last_response

    @property
    def is_ok(self):
        if self.last_response is None:
            return True
        if isinstance(self.last_response, tuple):
            return reduce(lambda x, y: x and self.check_function(y), self.last_response, True)
        return self.check_function(self.last_response)

    @contextlib.contextmanager
    def asserting(self, value=True, check_function=None):
        '''turn on/off asserting responses in self.send()'''
        old_value = self._asserting
        self._asserting = value
        old_check_function = self.check_function
        if check_function is not None:
            self.check_function = check_function

        try:
            yield
        finally:
            self._asserting = old_value
            self.check_function = old_check_function

    @contextlib.contextmanager
    def async(self, timeout=None):
        '''enter a async/concurent--send context; pending requests will be processed at context exit'''
        with self._semaphore:
            if self._async:
                # avoid nesting
                raise RuntimeError('Already in async ctx: %s' % self)
            self.last_request = ()
            self._async = True

        def sender(request):
            with self._semaphore:
                return self.session.send(request)

        try:
            yield  # gather send requests here
            # process pending requests
            jobs = [gevent.spawn(sender, request) for request in self.last_request]
            gevent.joinall(jobs, timeout=timeout, raise_error=True)
            self.last_response = tuple([job.value for job in jobs])
            if self._asserting:
                assert self.is_ok, 'pulp was not OK:\n' + \
                    format_preprequest(preprequest) + format_response(self.last_response)
        finally:
            self._async = False

    @property
    def pubkey(self):
        '''fetch pulp's public key'''
        if self._pubkey:
            return self._pubkey
        with self.asserting(True):
            response = self.send(StaticRequest('GET', 'rsa_pub.key'))
        assert response.content, "got empty content: %s" % format_response(response)
        self._pubkey = RSA.load_pub_key_bio(BIO.MemoryBuffer(response.content))
        return self._pubkey


class Request(object):
    pulp_path = pulp_path
    '''a callable request compatible with Pulp.send''' 
    def __init__(self, method, path='/', data={}, headers=cidict({'content-type': 'application/json'}),
            params={}):
        self.method = method
        self.path = path
        if 'content-type' in headers and headers['content-type'] == 'application/json':
            self.data = json.dumps(data)
        else:
            self.data = data
        self.headers = headers
        self.params = params

    def __call__(self, url, auth):
        return requests.Request(
            self.method,
            normalize_url(path_join(url, self.pulp_path, self.path)),
            params=self.params,
            auth=auth,
            data=self.data,
            headers=self.headers
        ).prepare()

    def __repr__(self):
        return self.__class__.__name__ + "(%r, %r, data=%r, headers=%r)" % (self.method, self.path, self.data, self.headers)


class StaticRequest(Request):
    '''a request into different pulp path'''
    pulp_path = pulp_static_path

    def __call__(self, url, auth):
        return requests.Request(
            self.method,
            normalize_url(path_join(url, self.pulp_path, self.path)).strip('/'),
            params=self.params,
            auth=auth,
            data=self.data,
            headers=self.headers
        ).prepare()


class ResponseLike(object):
    '''provide comparison between requests.Result and a code/text/data container'''
    def __init__(self, status_code=200, text=None):
        self.status_code = status_code
        self.text = text

    def __eq__(self, other):
        try:
            if self.text is not None:
                return self.status_code, self.text == other.status_code, other.text
            return self.status_code == other.status_code
        except AttributeError:
            return False

    def __repr__(self):
        return type(self).__name__ + '(status_code=%(status_code)s, text=%(text)s)' % self.__dict__


def format_response(response):
    '''format some response attributes'''
    import pprint
    try:
        text = pprint.pformat(response.json())
    except Exception:
        text = response.text
    return '>response:\n>c %s\n>u %s\n>t\n%s\n' % (response.status_code, response.url, text)


def format_preprequest(preprequest):
    '''format some prepared request attributes'''
    return '>preprequest:\n>m %(method)s\n>p %(url)s\n>b %(body)s\n>h %(headers)s\n' % preprequest.__dict__
