import os
from time import time, localtime

import RecordTimer
import Components.ParentalControl
from Screen import Screen
from Components.ActionMap import ActionMap
from Components.config import config
from Components.AVSwitch import AVSwitch
from Components.Console import Console
from Components.Harddisk import internalHDDNotSleeping
from Components.SystemInfo import SystemInfo
from GlobalActions import globalActionMap
from enigma import eDVBVolumecontrol, eTimer, eDVBLocalTimeHandler, eServiceReference
from Tools.HardwareInfo import HardwareInfo

inStandby = None

class Standby(Screen):
	def Power(self):
		print "[Standby] leave standby"
		self.close(True)

	def setMute(self):
		self.wasMuted = eDVBVolumecontrol.getInstance().isMuted()
		if not self.wasMuted:
			eDVBVolumecontrol.getInstance().volumeMute()

	def leaveMute(self):
		if not self.wasMuted:
			eDVBVolumecontrol.getInstance().openMixerOnMute() # fix for vuplus
			eDVBVolumecontrol.getInstance().volumeUnMute()

	def __init__(self, session, StandbyCounterIncrease=True):
		Screen.__init__(self, session)
		self.avswitch = AVSwitch()

		print "[Standby] enter standby"

		if os.path.exists("/usr/script/standby_enter.sh"):
			Console().ePopen("/usr/script/standby_enter.sh")

		self["actions"] = ActionMap( [ "StandbyActions" ],
		{
			"power": self.Power,
			"discrete_on": self.Power
		}, -1)

		globalActionMap.setEnabled(False)

		from Screens.InfoBar import InfoBar
		from Screens.SleepTimerEdit import isNextWakeupTime
		self.infoBarInstance = InfoBar.instance
		self.StandbyCounterIncrease = StandbyCounterIncrease
		self.standbyTimeoutTimer = eTimer()
		self.standbyTimeoutTimer.callback.append(self.standbyTimeout)
		self.standbyStopServiceTimer = eTimer()
		self.standbyStopServiceTimer.callback.append(self.stopService)
		self.standbyWakeupTimer = eTimer()
		self.standbyWakeupTimer.callback.append(self.standbyWakeup)
		self.timeHandler = None

		self.setMute()

		self.paused_service = self.paused_action = False

		self.prev_running_service = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if Components.ParentalControl.parentalControl.isProtected(self.prev_running_service):
			self.prev_running_service = eServiceReference(config.tv.lastservice.value)
		service = self.prev_running_service and self.prev_running_service.toString()
		if service:
			if service.rsplit(":", 1)[1].startswith("/"):
				self.paused_service = hasattr(self.session.current_dialog, "pauseService") and hasattr(self.session.current_dialog, "unPauseService") and self.session.current_dialog or self.infoBarInstance
				self.paused_action = hasattr(self.paused_service, "seekstate") and hasattr(self.paused_service, "SEEK_STATE_PLAY") and self.paused_service.seekstate == self.paused_service.SEEK_STATE_PLAY
				self.paused_action and self.paused_service.pauseService()
		if not self.paused_service:
			self.timeHandler =  eDVBLocalTimeHandler.getInstance()
			if self.timeHandler.ready():
				if self.session.nav.getCurrentlyPlayingServiceOrGroup():
					self.stopService()
				else:
					self.standbyStopServiceTimer.startLongTimer(5)
				self.timeHandler = None
			else:
				self.timeHandler.m_timeUpdated.get().append(self.stopService)

		if self.session.pipshown:
			self.infoBarInstance and hasattr(self.infoBarInstance, "showPiP") and self.infoBarInstance.showPiP()

		if SystemInfo["ScartSwitch"]:
			self.avswitch.setInput("SCART")
		else:
			self.avswitch.setInput("AUX")

		gotoShutdownTime = int(config.usage.standby_to_shutdown_timer.value)
		if gotoShutdownTime:
			self.standbyTimeoutTimer.startLongTimer(gotoShutdownTime)

		gotoWakeupTime = isNextWakeupTime(True)
		if gotoWakeupTime != -1:
			curtime = localtime(time())
			if curtime.tm_year > 1970:
				wakeup_time = int(gotoWakeupTime - time())
				if wakeup_time > 0:
					self.standbyWakeupTimer.startLongTimer(wakeup_time)

		self.onFirstExecBegin.append(self.__onFirstExecBegin)
		self.onClose.append(self.__onClose)

	def __onClose(self):
		global inStandby
		inStandby = None
		self.standbyTimeoutTimer.stop()
		self.standbyStopServiceTimer.stop()
		self.standbyWakeupTimer.stop()
		self.timeHandler and self.timeHandler.m_timeUpdated.get().remove(self.stopService)
		if self.paused_service:
			self.paused_action and self.paused_service.unPauseService()
		elif self.prev_running_service:
			service = self.prev_running_service.toString()
			if config.servicelist.startupservice_onstandby.value:
				self.session.nav.playService(eServiceReference(config.servicelist.startupservice.value))
				from Screens.InfoBar import InfoBar
				InfoBar.instance and InfoBar.instance.servicelist.correctChannelNumber()
			else:
				self.session.nav.playService(self.prev_running_service)
		self.session.screen["Standby"].boolean = False
		globalActionMap.setEnabled(True)
		if RecordTimer.RecordTimerEntry.receiveRecordEvents:
			RecordTimer.RecordTimerEntry.stopTryQuitMainloop()
		self.avswitch.setInput("ENCODER")
		self.leaveMute()
		if os.path.exists("/usr/script/standby_leave.sh"):
			Console().ePopen("/usr/script/standby_leave.sh")

	def __onFirstExecBegin(self):
		global inStandby
		inStandby = self
		self.session.screen["Standby"].boolean = True
		if self.StandbyCounterIncrease:
			config.misc.standbyCounter.value += 1

	def stopService(self):
		self.prev_running_service = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if Components.ParentalControl.parentalControl.isProtected(self.prev_running_service):
			self.prev_running_service = eServiceReference(config.tv.lastservice.value)
		self.session.nav.stopService()

	def createSummary(self):
		return StandbySummary

	def standbyTimeout(self):
		if config.usage.standby_to_shutdown_timer_blocktime.value:
			curtime = localtime(time())
			if curtime.tm_year > 1970: #check if the current time is valid
				curtime = (curtime.tm_hour, curtime.tm_min, curtime.tm_sec)
				begintime = tuple(config.usage.standby_to_shutdown_timer_blocktime_begin.value)
				endtime = tuple(config.usage.standby_to_shutdown_timer_blocktime_end.value)
				if begintime <= endtime and (curtime >= begintime and curtime < endtime) or begintime > endtime and (curtime >= begintime or curtime < endtime):
					duration = (endtime[0]*3600 + endtime[1]*60) - (curtime[0]*3600 + curtime[1]*60 + curtime[2])
					if duration:
						if duration < 0:
							duration += 24*3600
						self.standbyTimeoutTimer.startLongTimer(duration)
						return
		if self.session.screen["TunerInfo"].tuner_use_mask or internalHDDNotSleeping():
			self.standbyTimeoutTimer.startLongTimer(600)
		else:
			from RecordTimer import RecordTimerEntry
			RecordTimerEntry.TryQuitMainloop()

	def standbyWakeup(self):
		self.Power()

class StandbySummary(Screen):
	skin = """
	<screen position="0,0" size="132,64">
		<widget source="global.CurrentTime" render="Label" position="0,0" size="132,64" font="Regular;40" halign="center">
			<convert type="ClockToText" />
		</widget>
		<widget source="session.RecordState" render="FixedLabel" text=" " position="0,0" size="132,64" zPosition="1" >
			<convert type="ConfigEntryTest">config.usage.blinking_display_clock_during_recording,True,CheckSourceBoolean</convert>
			<convert type="ConditionalShowHide">Blink</convert>
		</widget>
	</screen>"""

from enigma import quitMainloop, iRecordableService
from Screens.MessageBox import MessageBox
from time import time
from Components.Task import job_manager


class QuitMainloopScreen(Screen):
	def __init__(self, session, retvalue=1):
		self.skin = """<screen name="QuitMainloopScreen" position="fill" flags="wfNoBorder">
				<ePixmap pixmap="skin_default/icons/input_info.png" position="c-27,c-60" size="53,53" alphatest="on" />
				<widget name="text" position="center,c+5" size="720,100" font="Regular;22" halign="center" />
			</screen>"""
		Screen.__init__(self, session)
		from Components.Label import Label
		text = { 1: _("Your receiver is shutting down"),
			2: _("Your receiver is rebooting"),
			3: _("The user interface of your receiver is restarting"),
			4: _("Your frontprocessor will be upgraded\nPlease wait until your receiver reboots\nThis may take a few minutes"),
			5: _("The user interface of your receiver is restarting\ndue to an error in mytest.py"),
			42: _("Unattended upgrade in progress\nPlease wait until your receiver reboots\nThis may take a few minutes") }.get(retvalue)
		self["text"] = Label(text)

inTryQuitMainloop = False

class TryQuitMainloop(MessageBox):
	def __init__(self, session, retvalue=1, timeout=-1, default_yes = False):
		self.retval = retvalue
		recordings = session.nav.getRecordings()
		jobs = len(job_manager.getPendingJobs())
		self.connected = False
		reason = ""
		next_rec_time = -1
		if not recordings:
			next_rec_time = session.nav.RecordTimer.getNextRecordingTime()
		if recordings or (next_rec_time > 0 and (next_rec_time - time()) < 360):
			reason = _("Recording(s) are in progress or coming up in few seconds!") + '\n'
		if jobs:
			if jobs == 1:
				job = job_manager.getPendingJobs()[0]
				reason += "%s: %s (%d%%)\n" % (job.getStatustext(), job.name, int(100*job.progress/float(job.end)))
			else:
				reason += (ngettext("%d job is running in the background!", "%d jobs are running in the background!", jobs) % jobs) + '\n'
		if reason:
			text = { 1: _("Really shutdown now?"),
				2: _("Really reboot now?"),
				3: _("Really restart now?"),
				4: _("Really upgrade the frontprocessor and reboot now?"),
				42: _("Really upgrade your settop box and reboot now?") }.get(retvalue)
			if text:
				MessageBox.__init__(self, session, reason+text, type = MessageBox.TYPE_YESNO, timeout = timeout, default = default_yes)
				self.skinName = "MessageBoxSimple"
				session.nav.record_event.append(self.getRecordEvent)
				self.connected = True
				self.onShow.append(self.__onShow)
				self.onHide.append(self.__onHide)
				return
		self.skin = """<screen position="0,0" size="0,0"/>"""
		Screen.__init__(self, session)
		self.close(True)

	def getRecordEvent(self, recservice, event):
		if event == iRecordableService.evEnd:
			recordings = self.session.nav.getRecordings()
			if not recordings: # no more recordings exist
				rec_time = self.session.nav.RecordTimer.getNextRecordingTime()
				if rec_time > 0 and (rec_time - time()) < 360:
					self.initTimeout(360) # wait for next starting timer
					self.startTimer()
				else:
					self.close(True) # immediate shutdown
		elif event == iRecordableService.evStart:
			self.stopTimer()

	def close(self, value):
		if self.connected:
			self.connected=False
			self.session.nav.record_event.remove(self.getRecordEvent)
		if value:
			self.hide()
			if self.retval == 1:
				config.misc.DeepStandby.value = True
				if not inStandby:
					if os.path.exists("/usr/script/standby_enter.sh"):
						Console().ePopen("/usr/script/standby_enter.sh")
					if SystemInfo["HasHDMI-CEC"] and config.hdmicec.enabled.value and config.hdmicec.control_tv_standby.value and config.hdmicec.next_boxes_detect.value:
						import Components.HdmiCec
						Components.HdmiCec.hdmi_cec.secondBoxActive()
						self.delay = eTimer()
						self.delay.timeout.callback.append(self.quitMainloop)
						self.delay.start(1500, True)
						return
			elif not inStandby:
				config.misc.RestartUI.value = True
				config.misc.RestartUI.save()
			self.quitMainloop()
		else:
			MessageBox.close(self, True)

	def quitMainloop(self):
		self.session.nav.stopService()
		self.quitScreen = self.session.instantiateDialog(QuitMainloopScreen, retvalue=self.retval)
		self.quitScreen.show()
		quitMainloop(self.retval)

	def __onShow(self):
		global inTryQuitMainloop
		inTryQuitMainloop = True

	def __onHide(self):
		global inTryQuitMainloop
		inTryQuitMainloop = False
