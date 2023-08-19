import unittest

from airflow.models import DagBag


class TestBashOperatorDAG(unittest.TestCase):
    """Check BashOperatorDAG expectation"""

    def setUp(self):
        self.dagbag = DagBag(dag_folder="./bash_dag.py", include_examples=False)

    def test_dag_loaded(self):
        """Check the dag is correctly loaded"""
        dag = self.dagbag.get_dag(dag_id="example_bash_operator")
        self.assertDictEqual(self.dagbag.import_errors, {})
        self.assertIsNotNone(dag)

    def test_dag_contains_tasks(self):
        """Check that the DAG has the expected tasks"""
        dag = self.dagbag.get_dag(dag_id="example_bash_operator")
        self.assertEqual(
            set(task.task_id for task in dag.tasks),
            {
                "run_this_last",
                "run_after_loop",
                "runme_0",
                "runme_1",
                "runme_2",
                "also_run_this",
                "this_will_skip",
            },
        )

    def test_dependencies_of_task(self):
        """Check the task dependencies of run_after_loop task in example_bash_operator DAG"""
        dag = self.dagbag.get_dag(dag_id="example_bash_operator")
        run_after_loop_task = dag.get_task("run_after_loop")

        upstream_task_ids = {
            task.task_id for task in run_after_loop_task.upstream_list
        }
        self.assertEqual(upstream_task_ids, {"runme_0", "runme_1", "runme_2"})

        downstream_task_ids = {
            task.task_id for task in run_after_loop_task.downstream_list
        }
        self.assertEqual(downstream_task_ids, {"run_this_last"})


if __name__ == "__main__":
    unittest.main()
