import item, time, hasdata
from item import (Item, GroupItem)
from pulp_auto.pulp import Request
from pulp_auto import strip_url

class TaskError(AssertionError):
   '''super class for task failures'''
   def __init__(self, *args, **kvs):
        '''save the task for reference'''
        self.task = kvs.pop('task', None)
        super(TaskError, self).__init__(*args, **kvs)

   def __str__(self):
        return super(TaskError, self).__str__() + ": %s" % self.task


class TaskFailure(TaskError):
    '''task failed'''

class TaskTimeoutError(TaskError):
    '''task timed out'''

class AbstractTask(object):
    state = None
    active_states = []
    end_states = []
    error_states = []

    def update(self, pulp):
        '''an abstract update does nothing'''
        pass

    def wait(self, pulp, timeout=120, frequency=0.5):
        '''wait while all of these conditions hold:
             - self.state in self.active_states
             - self.state not in self.end_states
             - timeout not elapsed yet
        '''
        delta = time.time() + timeout
        while time.time() <= delta:
            time.sleep(frequency)
            try:
                self.reload(pulp)
            except AssertionError as e:
                # task gone --- no need to wait anymore
                break
            if self.state in self.end_states:
                break
        else:
            raise TaskTimeoutError('Waiting exceeded %r second(s)' % timeout, task=self)
        if self.state in self.error_states:
            raise TaskFailure('Task failed: %r' % self.data['error'], task=self)

class TaskDetails(hasdata.HasData):
    relevant_data_keys = [
        "error",
        "state",
        "task_id",
        "progress_report",
        "result",
        "exception",
        "traceback",
        "start_time",
        "finish_time",
        "tags"
    ]
    required_data_keys = ['task_id', 'state']
    active_states = ['running', 'waiting']
    end_states = ['finished', 'error', 'canceled', 'cancelled']
    error_states = ['error']

    @property
    def state(self):
        return self.data['state']

    @property
    def id(self):
        return self.data['task_id']

    @id.setter
    def id(self, other):
        self.data['task_id'] = other


class Task(TaskDetails, AbstractTask, Item):
    '''an item-view task'''
    path = '/tasks/'

    @classmethod
    def wait_for_response(cls, pulp, response, timeout=120):
        '''a shortcut for wait & from_response'''
        ret = cls.from_response(response)
        if isinstance(ret, list):
            # more than one task pending
            for task in ret:
                task.wait(pulp, timeout=timeout)
        else:
            ret.wait(pulp, timeout=timeout)

    @classmethod
    def wait_for_report(cls, pulp, response, timeout=300):
        # now every asyncronous call returns a call report object
        # call report has 'spawned_tasks' that contains list of tasks
        # meanwhile every tasks can have its own spawned tasks
        ret = cls.from_report(response)['spawned_tasks']
        if isinstance(ret, list):
            for task in ret:
                task_resp = pulp.send(Request('GET', strip_url(task['_href'])))
                Task.wait_for_response(pulp, task_resp, timeout=timeout)
                task_resp = pulp.send(Request('GET', strip_url(task['_href'])))
                if 'spawned_tasks' in Task.from_response(task_resp).data:
                    Task.wait_for_report(pulp, task_resp, timeout=timeout)

    @classmethod
    def wait_for_reports(cls, pulp, responses, timeout=300):
        # a wrapper for multiple task report waiting
        # will take up to sum(tasks.time)
        # single-exception breaks
        for response in responses:
            cls.wait_for_report(pulp, response, timeout)


TASK_DATA_EXAMPLE = {
 "_href": "/pulp/api/v2/tasks/0fe4fcab-a040-11e1-a71c-00508d977dff/",
 "state": "running",
 "task_id": "0fe4fcab-a040-11e1-a71c-00508d977dff",
 "progress": {}, # contents depend on the operation
 "result": None,
 "start_time": "2012-05-17T16:48:00Z",
 "finish_time": None,
 "tags": [
   "pulp:repository:f16",
   "pulp:action:sync"
 ],
 "spawned_tasks": [{"href": "/pulp/api/v2/tasks/7744e2df-39b9-46f0-bb10-feffa2f7014b/",
                    "task_id": "7744e2df-39b9-46f0-bb10-feffa2f7014b" }],
 "error": None
}
