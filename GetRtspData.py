import socket,time,string,random,_thread
import re
import cv2
import logging
import os
import xlrd
from xlutils.copy import copy
from urllib.parse import urlparse
from dahua.auth import DigestAuth
from threading import Timer
# from dahua.nal_unit import NalUnit
from dahua.rtp_datagram import RTPDatagram
import av
import collections
from dahua.RTP_Resolving import RTPResolving
from dahua.nal_unit import NalUnitError
from dahua.nal_unit import NalUnit
from struct import unpack

m_Vars = {
    "bufLen": 1024*50,
    # "defaultUserName": "admin",     # RTSP�û���
    # "defaultPasswd": "wanji123",     # RTSP�û�����Ӧ����
    # "defaultServerIp": "192.168.2.101",  # RTSP������IP��ַ
    # "defaultServerPort": 554,           # RTSP������ʹ�ö˿�
    # "defaultTestUrl": "rtsp://192.168.2.101:554",
    # "LicenceUrl": "rtsp://admin:wanji123@192.168.2.101:554",
    "defaultUserAgent": "LibVLC/3.0.8 (LIVE555 Streaming Media v2016.11.28)" # "LibVLC/2.0.3 (LIVE555 Streaming Media v2011.12.23)"
}
# ���㵱ǰʱ�䵽2090���ж��ٸ�����
count1 = -1

for i in range(2020, 2090):
    if (i % 4 == 0 and i % 100 != 0 or i % 400 == 0):
        count1 = count1 + 1
# print('������%d��' % count1)
nweimiao = 1000*60*60*24*365*70 + 1000*60*60*24*count1

class RTSPClientError(Exception):
    pass


class RTSPClientRetryError(RTSPClientError):
    pass


class RTSPClientFatalError(RTSPClientError):
    pass

class GetRtspData(Exception):
    def __init__(self, url):
        self.codec = av.CodecContext.create('h264', 'r')
        # ����url
        self.username = None
        self.password = None
        self.host = None
        self.ip = None
        self.port = 554
        # self.path = None
        self.path = ''
        self.LicenceUrl = ''
        # self.safe_url = None
        self.url = url
        self._cseq = 0
        self._socket = None
        self._session = None
        self._realm = None
        self._nonce = None
        self._auth = None
        self._auth_attempts = 0
        self.nal_payload = b''
        self._RecvRtspLen = 0

    def response1(self, method):
        auth = DigestAuth(self.username, self.password, self._realm, self._nonce, method.upper(),
                          uri=self.LicenceUrl)
        responses = auth.header
        print(responses)
        return responses

    def genmsg_OPTIONS(self, userAgent):
        msgRet = "OPTIONS " + self.LicenceUrl + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "\r\n"
        return msgRet

    def genmsg_OPTIONS2(self, userAgent):
        method = "OPTIONS "
        respon = self.response1("OPTIONS")
        msgRet = method + self.LicenceUrl + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += 'Authorization:'
        msgRet += 'Digest username=\"' + self.username + '\"'
        msgRet += ', realm=\"' + self._realm + '\"'
        msgRet += ', nonce=\"' + self._nonce + '\"'
        msgRet += ', uri=\"' + self.LicenceUrl + '\"'
        msgRet += ', response=\"' + respon + "\"\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "\r\n"
        print(msgRet)
        return msgRet

    def genmsg_DESCRIBE(self, userAgent):
        msgRet = "DESCRIBE " + self.LicenceUrl + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "Accept: application/sdp\r\n"
        msgRet += "\r\n"
        return msgRet

    def genmsg_SETUP(self, userAgent):
        msgRet = "SETUP " + self.LicenceUrl + "/trackID=0" + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n"
        msgRet += "\r\n"
        return msgRet

    def genmsg_SETUP2(self, userAgent):
        msgRet = "SETUP " + self.LicenceUrl + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "Transport: RTP/AVP/TCP;unicast;interleaved=2-3\r\n"
        msgRet += "Session: " + str(self._session) + "\r\n"
        msgRet += "\r\n"
        return msgRet

    def genmsg_PLAY(self, userAgent):
        msgRet = "PLAY " + self.LicenceUrl + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "Session: " + self._session + "\r\n"
        msgRet += "\r\n"
        return msgRet

    def genmsg_TEARDOWN(self, userAgent):
        msgRet = "TEARDOWN " + self.LicenceUrl + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "Session: " + self._session + "\r\n"
        msgRet += "\r\n"
        return msgRet

    def decodeMsg(strContent):
        mapRetInf = {}
        for str in [elem for elem in strContent.split("\n") if len(elem) > 1][2:-1]:
            print(str)
            tmp2 = str.split(":")
            mapRetInf[tmp2[0]] = tmp2[1][:-1]
            print(mapRetInf)
        return mapRetInf

    def _parse_digest_auth_header(self, header):
        self._realm = re.search(r'realm=\"([^\"]+)\"', str(header)).group(1)
        self._nonce = re.search(r'nonce=\"([\w]+)\"', str(header)).group(1)

    def SendHeart(self, socktp, userAgent):
        msgRet = "GET_PARAMETER " + self.LicenceUrl + " RTSP/1.0\r\n"
        msgRet += "CSeq: " + str(self._cseq) + "\r\n"
        msgRet += "User-Agent: " + userAgent + "\r\n"
        msgRet += "Session: " + self._session + "\r\n"
        msgRet += "\r\n"
        socktp.send(bytes(msgRet, 'utf-8'))
        # data = socktp.recv(50)
        # print(data)

    @property
    def url(self):
        return self.__url

    @url.setter
    def url(self, url):
        parsed = urlparse(url)
        if parsed.scheme != "rtsp":
            raise RTSPClientFatalError(
                f'Protocol mismatch: expecting "rtsp", got "{parsed.scheme}"')
        try:
            self.host = parsed.hostname
            self.ip = socket.gethostbyname(self.host)
            # print(self.host)
            # print(self.ip)
        except:
            raise RTSPClientFatalError(
                f'Failed to resolve {parsed.hostname} to IP address')
        self.username = parsed.username
        self.password = parsed.password
        self.port = parsed.port
        if len(parsed.path) > 0 or len(parsed.query) > 0:
            self.path = parsed.path + '?' + parsed.query
        else:
            self.path = ''
        self.LicenceUrl = f'rtsp://{self.username}:{self.password}@{self.host}:{self.port}{self.path}'
        print(self.LicenceUrl)
        self.__url = url

    def ConnectCamera(self):
        try:
            print("3424223232323232")
            # �������
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.connect((self.ip, self.port))
            self._cseq = 1
        except socket.error as e:
            print("Connected Error!")
            print(e)
    def options(self):
        # print(genmsg_OPTIONS(m_Vars["defaultTestUrl"], seq, m_Vars["defaultUserAgent"]))
        sends = self._socket.send(
            bytes(self.genmsg_OPTIONS(m_Vars["defaultUserAgent"]), 'utf-8'))
        # print("genmsg_OPTIONS Send:" + str(sends))
        data = self._socket.recv(m_Vars["bufLen"])
        self._parse_digest_auth_header(data)
        self._cseq = self._cseq + 1

        sends = self._socket.send(
            bytes(self.genmsg_OPTIONS2(m_Vars["defaultUserAgent"]), 'utf-8'))
        # print("genmsg_OPTIONS2 Send:" + str(sends))
        data = self._socket.recv(m_Vars["bufLen"])
        self._cseq = self._cseq + 1

    def describe(self):
        self._socket.send(bytes(self.genmsg_DESCRIBE(m_Vars["defaultUserAgent"]), 'utf-8'))
        msg1 = self._socket.recv(m_Vars["bufLen"])
        # print(str(msg1))
        self._cseq = self._cseq + 1

    def setup(self):
        self._socket.send(bytes(self.genmsg_SETUP(m_Vars["defaultUserAgent"]), 'utf-8'))
        msg1 = self._socket.recv(m_Vars["bufLen"])
        self._cseq = self._cseq + 1
        recv_msg1 = msg1.decode()
        session_pos = recv_msg1.find('Session')
        session_value_begin_pos = recv_msg1.find(' ', session_pos + 8) + 1
        session_value_end_pos = recv_msg1.find(';', session_pos + 8)
        self._session = recv_msg1[session_value_begin_pos:session_value_end_pos]
        self._RecvRtspLen = len(self._session) + 39

    def play(self):
        self._socket.send(bytes(self.genmsg_PLAY(m_Vars["defaultUserAgent"]), 'utf-8'))
        msg1 = self._socket.recv(m_Vars["bufLen"])
        # print(msg1)
        self._cseq = self._cseq + 1

    def _close(self):
        # self._socket.send(bytes(self.genmsg_TEARDOWN(m_Vars["defaultUserAgent"]), 'utf-8'))
        self._socket.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_t, exc_v, traceback):
        # self._socket.send(bytes(self.genmsg_TEARDOWN(m_Vars["defaultUserAgent"]), 'utf-8'))
        self._close()

    def __del__(self):
        self._close()

    def ping(self):
        ''' ping  '''
        strip = ("ping " + self.ip)
        result = os.system(str(strip))
        # result = os.system(u"ping www.baidu.com -n 3")
        if result == 0:
            print("Success")
        else:
            print("Failed")
        return result

    def StartPlay(self):
        self.ConnectCamera()
        self.options()
        self.describe()
        self.setup()
        self.play()
        i = 0
        while True:
            try:
            # s.send(genmsg_ANNOUNCE(m_Vars["defaultServerIp"]))
                if self._socket._closed:
                    continue
                msg_recv = self._socket.recv(4)
                t = time.time()
                if 4 > len(msg_recv):
                    msg_recv += self._socket.recv(4 - len(msg_recv))
                if len(msg_recv) == 0:
                    continue
                # ��ȡRTP_HEADER
                TcpH_magic = unpack('!B', msg_recv[:1])[0]
                TcpH_channel = unpack('!B', msg_recv[1:2])[0]
                TcpH_length = unpack('!B', msg_recv[2:3])[0] << 8 | unpack('!B', msg_recv[3:4])[0]
                if TcpH_magic == 0x24:
                    DataBuff = self._socket.recv(TcpH_length)
                    if TcpH_length > len(DataBuff):
                        DataBuff += self._socket.recv(TcpH_length - len(DataBuff))
                    RtpOrRtcp = unpack('!B', DataBuff[1:2])[0]
                    RtpOrRtcp = RtpOrRtcp & 0b01100000
                    # ����RTPЭ��
                    if DataBuff and RtpOrRtcp == 96:
                        # RTP��
                        rtp_data = RTPDatagram(DataBuff)
                        # ���δ������payload
                        nal_payload_temp = rtp_data.payload
                        # ͨ��NALU��ý������H264����
                        nal_parse = NalUnit(nal_payload_temp)
                        # �жϵ�ǰ�Ƿ�Ϊ��β
                        if nal_parse.fragment_end == 0:
                            self.nal_payload = self.nal_payload + nal_parse.payload
                            continue
                        elif nal_parse.fragment_end == 1:
                            # print("2@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
                            # ��ǰΪ֡��β
                            s_data = rtp_data.s_data
                            ms_data = rtp_data.ms_data
                            RTP_time = str(s_data) + "" + str(ms_data)
                            if ms_data < 10:
                                RTP_time = str(s_data) + "00" + str(ms_data)
                            elif ms_data < 100:
                                RTP_time = str(s_data) + "0" + str(ms_data)
                            self.nal_payload = self.nal_payload + nal_parse.payload
                            packets = self.codec.parse(self.nal_payload)
                            print("Parsed {} packets from {} bytes:".format(len(packets), len(self.nal_payload)))

                            file = open(r"D:\NetErrorTime.txt", 'a')
                            file.write(str(int(RTP_time) - nweimiao) + '\n')
                            file.write(str(int(round(t * 1000))) + '\n')
                            file.close()

                            for packet in packets:
                                frames = self.codec.decode(packet)
                                for frame in frames:
                                    # print("process frame: %04d (width: %d, height: %d)" % (
                                    # frame.index, frame.width, frame.height))
                                    img = frame.to_ndarray(format='bgr24')

                                    yield img, RTP_time, self.nal_payload

                                    # cv2.namedWindow('Video', cv2.WINDOW_GUI_NORMAL)
                                    # cv2.imshow("Video", img)
                                if cv2.waitKey(1) & 0xFF == ord('q'):
                                    self.nal_payload = b''
                                    break
                            self.nal_payload = b''
                            i = i + 1
                            if i % 10 == 0:
                                self.SendHeart(self._socket, m_Vars["defaultUserAgent"])
                    else:
                        # ��RTP�������д���
                        continue
                else:
                    # ������rtp��
                    data = self._socket.recv(self._RecvRtspLen - 4)
                    # print(data)
            except socket.error as e:
                # ���������쳣
                logging.basicConfig(level=logging.DEBUG,  # ����̨��ӡ����־����
                                    filename='D:\\GetRstpData.log',
                                    filemode='a',  ##ģʽ����w��a��w����дģʽ��ÿ�ζ�������д��־������֮ǰ����־
                                    # a��׷��ģʽ��Ĭ�������д�Ļ�������׷��ģʽ
                                    format=
                                    '%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s'
                                    # ��־��ʽ
                                    )
                logging.error(e)

                self._socket.shutdown(2)
                self._socket.close()
                time.sleep(30)
                self.ping()
                if self._socket._closed:
                    self.ConnectCamera()
                print("2222222222222222222")





