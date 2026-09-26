from locust import HttpUser, task, between


class ChatUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def top_customers(self):
        self.client.post("/chat", json={"question": "Who are the top customers?"})

    @task(2)
    def popular_genre(self):
        self.client.post("/chat", json={"question": "What is the most popular genre?"})

    @task(1)
    def revenue_by_country(self):
        self.client.post("/chat", json={"question": "What is the total revenue per country?"})
