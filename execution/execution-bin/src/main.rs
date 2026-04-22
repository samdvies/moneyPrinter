use anyhow::Result;

#[tokio::main]
async fn main() -> Result<()> {
    execution_bin::run().await?;
    Ok(())
}
