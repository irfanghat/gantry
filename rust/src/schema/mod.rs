#[derive(Debug, Clone)]
pub struct RetryConfig {
    max_attempts: i32,
    wait_seconds: f32,
    on_exceptions: Vec<String>,
    on_status_codes: Vec<i32>,
}

