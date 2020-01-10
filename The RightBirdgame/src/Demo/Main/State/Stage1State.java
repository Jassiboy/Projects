package Demo.Main.State;

import Demo.Main.Entity.Bird;
import Demo.Main.Entity.Entity;
import Demo.Main.Entity.Log;
import Demo.Main.GamePanel;
import Demo.Main.RandomGenerator;
import Demo.Main.Resources;

import java.awt.*;
import java.awt.event.KeyEvent;
import java.util.ArrayList;
import java.util.List;


/**
 * Created by jassiboy on 2/26/2017.
 */
public class Stage1State extends State {
   // private static final int GROUND_Y_CORD = 315;


    private int logsCrossed = 0;
    private int  background1ImageXcord = 0;
    private List<Log> logs;
    private Bird bird;
    private List<Entity> entities;

    public Stage1State() {
        super();

        logs = new ArrayList<>();
        entities = new ArrayList<>();

        logs.add(new Log(900, 55));
        //logs.add(new Log(900, 55));
       // logs.add(new Log(1100, 100));
        //logs.add(new Log(1100, 155));
        logs.add(new Log(1300, 255));
       // logs.add(new Log(1500, 355));
        logs.add(new Log(900, 455));
       // logs.add(new Log(1700, 455));
        bird = new Bird(200, 50);

        entities.addAll(logs);
        entities.add(bird);
    }


    @Override
    public void update() {
        for(Entity e: entities) {
            e.update();
        }
        background1ImageXcord -=5;
        for (Log b: logs) {
            if(b.xCord < -20) {
                b.xCord = 980;

                if (RandomGenerator.getInt(0,4) == 0) {
                    b.yCord = 55;
                } else if (RandomGenerator.getInt(0, 5) == 1)
                    b.yCord = 155;
                else if (RandomGenerator.getInt(0,5) == 2)
                    b.yCord=285;
                else {
                    b.yCord=370;
                }




                if(b.visible) {
                    logsCrossed++;

                    if(logsCrossed == 2) {
                        GamePanel.currentState = new Stage2State();
                      //  Resources.singAudio.play();
                    }
                }

                b.visible = true;

            }

            if(bird.isColldingWith(b)) {
                bird.xCord  -= 20;
                b.visible = false;
                Resources.flapAudio.play();
            }
            if (background1ImageXcord == -1300)
                background1ImageXcord = 0;
        }

        if(bird.yCord < 0) {
            bird.yCord = 0;
            bird.yVel = 26;
            bird.yAcc = 0;
        }

    }

    @Override
    public void render(Graphics g) {
        //g.setColor(Color.blue);
        //g.fillRect(0,0,800,450);

        g.drawImage(Resources.background1Image, background1ImageXcord, 0, null);
        g.drawImage(Resources.background1Image, background1ImageXcord+1300, 0, null);

        for(Entity e: entities) {
            if(e.visible) {
                g.drawImage(e.getImage(), e.xCord, e.yCord, null);
            }
        }


    }

    @Override
    public void onKeyPressed(int pressedKeyCode) {
        if(pressedKeyCode == KeyEvent.VK_UP ) {
            bird.yVel = -26;
            bird.yAcc = 2;
        } else if (pressedKeyCode == KeyEvent.VK_DOWN) {
            //bird.duck(true);
            bird.yVel = 26;
            bird.yAcc = 2;
        }
    }

    }

